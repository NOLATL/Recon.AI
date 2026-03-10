"""
Unit tests for src/services/probabilistic_matching.py

Tests every explicit requirement:

  [Threshold enforcement]
  - Pair above threshold → match
  - Pair below threshold → no match
  - Pair exactly at threshold → match (boundary inclusive)

  [Grouping size limit]
  - Group of MAX_GROUP_SIZE (5) is attempted
  - Group of MAX_GROUP_SIZE+1 (6) is NOT attempted (only up to 5 combined)

  [1:1 greedy — highest similarity first]
  - When two GL records could match the same Sub, higher-similarity one wins
  - Loser GL stays in residual

  [N:1 matching]
  - Two GL rows summing to one Sub amount → grouping_type="many_to_one"
  - Group similarity computed correctly
  - Matched records removed from residual

  [1:N matching]
  - One GL row matching sum of two Sub rows → grouping_type="one_to_many"
  - Matched records removed from residual

  [Blocking rules]
  - Different entity → blocked (no match)
  - Date > 60 days apart → blocked
  - Date exactly 60 days apart → passes block (boundary inclusive)
  - Date 61 days apart → blocked
  - Amount diff > tolerance band → blocked

  [Pool management]
  - Records matched in 1:1 not reused in N:1 or 1:N
  - Unmatched records appear in residual_gl / residual_sub

  [Edge cases]
  - Both pools empty → no matches, empty residuals
  - GL pool empty → no matches
  - Sub pool empty → no matches
  - Missing required GL column raises ValueError
  - Missing required Sub column raises ValueError
  - Single GL, single Sub with no match → both in residual

  [Result shape]
  - user_status == "pending" for all matches
  - override_flag == False for all matches
  - component_scores has keys: vendor_similarity, amount_similarity, date_similarity, entity_similarity
  - grouping_type in {"one_to_one", "many_to_one", "one_to_many"}
  - match_id is non-empty string
  - total_gl / total_sub equal input lengths
  - matched_gl + len(residual_gl) == total_gl
  - matched_sub + len(residual_sub) == total_sub
  - threshold_used == threshold parameter
  - weights_used == weights parameter
"""

import pandas as pd
import pytest

from src.services.probabilistic_matching import (
    DATE_TOLERANCE_DAYS,
    DEFAULT_THRESHOLD,
    DEFAULT_WEIGHTS,
    MAX_GROUP_SIZE,
    ProbabilisticResult,
    run_probabilistic_matching,
    _amount_sim,
    _date_sim,
    _entity_sim,
    _vendor_sim,
    _passes_block,
)


# ---------------------------------------------------------------------------
# DataFrame builders
# ---------------------------------------------------------------------------

def _gl(rows: list) -> pd.DataFrame:
    return pd.DataFrame(rows)


def _sub(rows: list) -> pd.DataFrame:
    return pd.DataFrame(rows)


def _gl_row(
    gl_id="GL001",
    vendor="vendor alpha",
    amount=100.00,
    date="2024-01-15",
    entity="CORP",
) -> dict:
    return {
        "gl_id":            gl_id,
        "Vendor_Normalized": vendor,
        "amount":           amount,
        "transaction_date": date,
        "entity":           entity,
    }


def _sub_row(
    sub_id="SUB001",
    vendor="vendor alpha",
    amount=100.00,
    date="2024-01-15",
    entity="CORP",
) -> dict:
    return {
        "subledger_id":     sub_id,
        "Vendor_Normalized": vendor,
        "amount":           amount,
        "transaction_date": date,
        "entity":           entity,
    }


def _run(gl_rows, sub_rows, threshold=DEFAULT_THRESHOLD, weights=None) -> ProbabilisticResult:
    return run_probabilistic_matching(
        _gl(gl_rows),
        _sub(sub_rows),
        threshold=threshold,
        weights=weights or DEFAULT_WEIGHTS,
    )


# ===========================================================================
# Similarity helper unit tests
# ===========================================================================

class TestSimilarityHelpers:
    def test_vendor_sim_identical(self):
        assert _vendor_sim("vendor alpha", "vendor alpha") == 1.0

    def test_vendor_sim_completely_different(self):
        assert _vendor_sim("aaaa", "zzzz") < 0.5

    def test_amount_sim_identical(self):
        assert _amount_sim(100.0, 100.0) == 1.0

    def test_amount_sim_zero_diff(self):
        assert _amount_sim(50.0, 50.0) == 1.0

    def test_amount_sim_large_diff(self):
        assert _amount_sim(100.0, 200.0) < 1.0

    def test_amount_sim_non_negative(self):
        # Very large difference should clamp to 0
        assert _amount_sim(1.0, 10000.0) >= 0.0

    def test_date_sim_same_date(self):
        assert _date_sim("2024-01-15", "2024-01-15") == 1.0

    def test_date_sim_at_tolerance(self):
        """Exactly at tolerance → sim = 0.0 (boundary)."""
        assert _date_sim("2024-01-01", "2024-03-01") == pytest.approx(0.0, abs=0.02)

    def test_date_sim_beyond_tolerance(self):
        """Past tolerance → clamped to 0.0."""
        assert _date_sim("2024-01-01", "2025-01-01") == 0.0

    def test_entity_sim_same(self):
        assert _entity_sim("CORP", "CORP") == 1.0

    def test_entity_sim_different(self):
        assert _entity_sim("CORP_A", "CORP_B") == 0.0


# ===========================================================================
# Blocking rules
# ===========================================================================

class TestBlockingRules:
    def test_different_entity_blocked(self):
        result = _run(
            [_gl_row(entity="CORP_A")],
            [_sub_row(entity="CORP_B")],
        )
        assert len(result.matches) == 0

    def test_same_entity_not_blocked(self):
        result = _run(
            [_gl_row(entity="CORP", vendor="vendor alpha", amount=100.0)],
            [_sub_row(entity="CORP", vendor="vendor alpha", amount=100.0)],
        )
        assert len(result.matches) == 1

    def test_date_exactly_60_days_passes(self):
        result = _run(
            [_gl_row(date="2024-01-01", amount=100.0)],
            [_sub_row(date="2024-03-01", amount=100.0)],  # 60 days
        )
        # With threshold 0.80 and date_sim~0 at boundary, may or may not match.
        # What matters: not blocked on date alone — test by lowering threshold.
        result_low = _run(
            [_gl_row(date="2024-01-01", amount=100.0)],
            [_sub_row(date="2024-03-01", amount=100.0)],
            threshold=0.0,
        )
        # Should produce a candidate (not blocked by date = 60 days)
        assert len(result_low.matches) == 1

    def test_date_61_days_blocked(self):
        result = _run(
            [_gl_row(date="2024-01-01")],
            [_sub_row(date="2024-03-03")],  # 62 days (Jan=31, Feb=29 in 2024, +2 more)
            threshold=0.0,
        )
        # 2024-01-01 to 2024-03-03 = 62 days (2024 is leap year: Jan 31d + Feb 29d + 3d = 63 days)
        # Let's use a clearer 61-day gap:
        result2 = _run(
            [_gl_row(date="2024-01-01")],
            [_sub_row(date="2024-03-02")],  # Jan(31) + Feb(29) + 1 = 61 days
            threshold=0.0,
        )
        assert len(result2.matches) == 0

    def test_amount_within_tolerance_passes(self):
        # $100 vs $104 = 4% diff, within 20% band
        result = _run(
            [_gl_row(amount=100.0)],
            [_sub_row(amount=104.0)],
            threshold=0.0,
        )
        assert len(result.matches) == 1

    def test_amount_outside_tolerance_blocked(self):
        # $100 vs $200 = 50% diff, well outside 20% band
        result = _run(
            [_gl_row(amount=100.0)],
            [_sub_row(amount=200.0)],
            threshold=0.0,
        )
        assert len(result.matches) == 0


# ===========================================================================
# Threshold enforcement
# ===========================================================================

class TestThresholdEnforcement:
    def test_identical_pair_above_threshold(self):
        """Identical vendor/amount/date/entity → similarity ~1.0, above any reasonable threshold."""
        result = _run([_gl_row()], [_sub_row()], threshold=0.80)
        assert len(result.matches) == 1

    def test_pair_below_threshold_no_match(self):
        """Force similarity below threshold using threshold=0.9999."""
        # Identical pair has similarity 1.0, so to get no match we need mismatched vendor+date+amount
        # Use slightly different vendor to get ~0.90 similarity, threshold=0.95 → no match
        result = _run(
            [_gl_row(vendor="vendor alpha corp", amount=101.0)],
            [_sub_row(vendor="vendor alpha",     amount=100.0)],
            threshold=0.999,
        )
        assert len(result.matches) == 0

    def test_pair_exactly_at_threshold_matches(self):
        """Pair exactly at threshold should match (inclusive boundary)."""
        result_base = _run([_gl_row()], [_sub_row()], threshold=0.0)
        assert len(result_base.matches) >= 1
        actual_sim = result_base.matches[0].final_similarity
        # Run again with threshold == exact similarity → still matches
        result_exact = _run([_gl_row()], [_sub_row()], threshold=actual_sim)
        assert len(result_exact.matches) == 1

    def test_pair_just_above_threshold_matches(self):
        result = _run([_gl_row()], [_sub_row()], threshold=0.50)
        assert len(result.matches) == 1

    def test_threshold_stored_in_result(self):
        result = _run([_gl_row()], [_sub_row()], threshold=0.75)
        assert result.threshold_used == 0.75


# ===========================================================================
# 1:1 greedy matching — highest similarity first
# ===========================================================================

class TestOneToOneMatching:
    def test_basic_1to1_match(self):
        result = _run([_gl_row()], [_sub_row()])
        assert len(result.matches) == 1
        assert result.matches[0].grouping_type == "one_to_one"

    def test_record_ids_correct(self):
        result = _run([_gl_row(gl_id="GL001")], [_sub_row(sub_id="SUB001")])
        m = result.matches[0]
        assert m.record_ids_A == ["GL001"]
        assert m.record_ids_B == ["SUB001"]

    def test_matched_records_removed_from_residual(self):
        result = _run([_gl_row()], [_sub_row()])
        assert len(result.residual_gl) == 0
        assert len(result.residual_sub) == 0

    def test_unmatched_records_remain_in_residual(self):
        result = _run(
            [_gl_row(entity="CORP_A")],
            [_sub_row(entity="CORP_B")],
        )
        assert len(result.residual_gl) == 1
        assert len(result.residual_sub) == 1

    def test_greedy_highest_similarity_wins(self):
        """
        GL001 (vendor alpha) vs SUB001 (vendor alpha, $100): high similarity
        GL002 (vendor beta)  vs SUB001: lower similarity

        Both GL rows could match SUB001, but GL001 should win.
        GL002 goes to residual.
        """
        result = _run(
            [
                _gl_row(gl_id="GL001", vendor="vendor alpha", amount=100.0),
                _gl_row(gl_id="GL002", vendor="vendor beta",  amount=100.0),
            ],
            [_sub_row(sub_id="SUB001", vendor="vendor alpha", amount=100.0)],
        )
        assert len(result.matches) == 1
        assert result.matches[0].record_ids_A == ["GL001"]
        # GL002 must be in residual
        residual_ids = set(result.residual_gl["gl_id"].tolist())
        assert "GL002" in residual_ids

    def test_multiple_1to1_matches(self):
        result = _run(
            [
                _gl_row(gl_id="GL001", vendor="vendor a", amount=100.0),
                _gl_row(gl_id="GL002", vendor="vendor b", amount=200.0),
            ],
            [
                _sub_row(sub_id="SUB001", vendor="vendor a", amount=100.0),
                _sub_row(sub_id="SUB002", vendor="vendor b", amount=200.0),
            ],
        )
        assert len(result.matches) == 2
        assert len(result.residual_gl) == 0
        assert len(result.residual_sub) == 0


# ===========================================================================
# N:1 grouping
# ===========================================================================

class TestNToOneMatching:
    def test_n_to_1_match(self):
        """Two GL rows summing to one Sub amount → many_to_one match."""
        result = _run(
            [
                _gl_row(gl_id="GL001", vendor="vendor alpha", amount=60.0),
                _gl_row(gl_id="GL002", vendor="vendor alpha", amount=40.0),
            ],
            [_sub_row(sub_id="SUB001", vendor="vendor alpha", amount=100.0)],
        )
        many_to_one = [m for m in result.matches if m.grouping_type == "many_to_one"]
        assert len(many_to_one) == 1

    def test_n_to_1_record_ids(self):
        result = _run(
            [
                _gl_row(gl_id="GL001", vendor="vendor alpha", amount=60.0),
                _gl_row(gl_id="GL002", vendor="vendor alpha", amount=40.0),
            ],
            [_sub_row(sub_id="SUB001", vendor="vendor alpha", amount=100.0)],
        )
        m = [m for m in result.matches if m.grouping_type == "many_to_one"][0]
        assert set(m.record_ids_A) == {"GL001", "GL002"}
        assert m.record_ids_B == ["SUB001"]

    def test_n_to_1_residual_cleared(self):
        result = _run(
            [
                _gl_row(gl_id="GL001", vendor="vendor alpha", amount=60.0),
                _gl_row(gl_id="GL002", vendor="vendor alpha", amount=40.0),
            ],
            [_sub_row(sub_id="SUB001", vendor="vendor alpha", amount=100.0)],
        )
        assert len(result.residual_gl) == 0
        assert len(result.residual_sub) == 0

    def test_n_to_1_not_accepted_below_threshold(self):
        """Group that passes amount band but different entity → blocked by entity grouping."""
        result = _run(
            [
                _gl_row(gl_id="GL001", vendor="vendor alpha", amount=60.0, entity="CORP_A"),
                _gl_row(gl_id="GL002", vendor="vendor alpha", amount=40.0, entity="CORP_A"),
            ],
            [_sub_row(sub_id="SUB001", vendor="vendor alpha", amount=100.0, entity="CORP_B")],
        )
        assert len(result.matches) == 0

    def test_n_to_1_requires_vendor_similarity(self):
        """GL rows with vendor similarity below VENDOR_SIM_MIN are filtered before combination."""
        result = _run(
            [
                _gl_row(gl_id="GL001", vendor="aardvark inc", amount=60.0),
                _gl_row(gl_id="GL002", vendor="aardvark inc", amount=40.0),
            ],
            [_sub_row(sub_id="SUB001", vendor="zyxwvut llc", amount=100.0)],
            threshold=0.0,  # Even at zero threshold: vendor pre-filter must block candidates
        )
        assert len(result.matches) == 0


# ===========================================================================
# 1:N grouping
# ===========================================================================

class TestOneToNMatching:
    def test_1_to_n_match(self):
        """One GL row matching sum of two Sub rows → one_to_many match."""
        result = _run(
            [_gl_row(gl_id="GL001", vendor="vendor alpha", amount=100.0)],
            [
                _sub_row(sub_id="SUB001", vendor="vendor alpha", amount=60.0),
                _sub_row(sub_id="SUB002", vendor="vendor alpha", amount=40.0),
            ],
        )
        one_to_many = [m for m in result.matches if m.grouping_type == "one_to_many"]
        assert len(one_to_many) == 1

    def test_1_to_n_record_ids(self):
        result = _run(
            [_gl_row(gl_id="GL001", vendor="vendor alpha", amount=100.0)],
            [
                _sub_row(sub_id="SUB001", vendor="vendor alpha", amount=60.0),
                _sub_row(sub_id="SUB002", vendor="vendor alpha", amount=40.0),
            ],
        )
        m = [m for m in result.matches if m.grouping_type == "one_to_many"][0]
        assert m.record_ids_A == ["GL001"]
        assert set(m.record_ids_B) == {"SUB001", "SUB002"}

    def test_1_to_n_residual_cleared(self):
        result = _run(
            [_gl_row(gl_id="GL001", vendor="vendor alpha", amount=100.0)],
            [
                _sub_row(sub_id="SUB001", vendor="vendor alpha", amount=60.0),
                _sub_row(sub_id="SUB002", vendor="vendor alpha", amount=40.0),
            ],
        )
        assert len(result.residual_gl) == 0
        assert len(result.residual_sub) == 0


# ===========================================================================
# Grouping size limit
# ===========================================================================

class TestGroupingSizeLimit:
    def test_group_of_max_size_accepted(self):
        """MAX_GROUP_SIZE GL rows summing to one Sub → should produce a match."""
        n = MAX_GROUP_SIZE
        per_row = 100.0 / n
        gl_rows = [_gl_row(gl_id=f"GL{i:03d}", vendor="vendor alpha", amount=per_row) for i in range(n)]
        result = _run(
            gl_rows,
            [_sub_row(sub_id="SUB001", vendor="vendor alpha", amount=100.0)],
        )
        # Should find the group of n matching
        n_to_1 = [m for m in result.matches if m.grouping_type == "many_to_one"]
        assert len(n_to_1) == 1
        assert len(n_to_1[0].record_ids_A) == n

    def test_group_larger_than_max_not_produced(self):
        """Service never returns a group with more than MAX_GROUP_SIZE records."""
        # Create enough rows that only a group of MAX_GROUP_SIZE+2 would exactly sum to target
        # (but the service caps at MAX_GROUP_SIZE, so it will not find it).
        # Use amounts where individual sums fall well outside tolerance for smaller groups:
        # Sub = 700.  Each GL row = 100.  5 rows = 500, diff=200, tol=max(20%*700,5)=140. 200>140 → fail.
        # 7 rows = 700 → would match, but 7 > MAX_GROUP_SIZE=5, so not attempted.
        n = MAX_GROUP_SIZE + 2  # 7
        gl_rows = [_gl_row(gl_id=f"GL{i:03d}", vendor="vendor alpha", amount=100.0) for i in range(n)]
        result = _run(
            gl_rows,
            [_sub_row(sub_id="SUB001", vendor="vendor alpha", amount=700.0)],
            threshold=0.0,
        )
        # No match should be produced (no valid subset of ≤ 5 sums to 700 within tolerance)
        assert len(result.matches) == 0


# ===========================================================================
# No deterministic mutation
# ===========================================================================

class TestNoDeterministicMutation:
    def test_probabilistic_does_not_alter_deterministic_matches(self):
        """
        If deterministic matches are in runtime["matching"]["deterministic"],
        probabilistic service must not touch them.
        """
        import src.core.runtime_manager as rm

        session_id = rm.create_session()
        det_list = [{"match_id": "DET001", "record_ids_A": ["GL001"], "record_ids_B": ["SUB001"]}]
        rm.write_matching_results(session_id, "deterministic", det_list)

        # Now run probabilistic matching on a residual pool
        result = _run(
            [_gl_row(gl_id="GL002", vendor="vendor beta", amount=50.0)],
            [_sub_row(sub_id="SUB002", vendor="vendor beta", amount=50.0)],
        )

        # Deterministic layer in runtime untouched
        runtime = rm.get_runtime(session_id)
        assert runtime["matching"]["deterministic"] == det_list


# ===========================================================================
# Edge cases
# ===========================================================================

class TestEdgeCases:
    def test_both_pools_empty(self):
        result = run_probabilistic_matching(
            pd.DataFrame(), pd.DataFrame()
        )
        assert len(result.matches) == 0
        assert len(result.residual_gl) == 0
        assert len(result.residual_sub) == 0

    def test_gl_pool_empty(self):
        sub = _sub([_sub_row()])
        result = run_probabilistic_matching(pd.DataFrame(), sub)
        assert len(result.matches) == 0

    def test_sub_pool_empty(self):
        gl = _gl([_gl_row()])
        result = run_probabilistic_matching(gl, pd.DataFrame())
        assert len(result.matches) == 0

    def test_no_match_all_in_residual(self):
        result = _run(
            [_gl_row(entity="CORP_A")],
            [_sub_row(entity="CORP_B")],
        )
        assert len(result.matches) == 0
        assert len(result.residual_gl) == 1
        assert len(result.residual_sub) == 1

    def test_missing_gl_column_raises_value_error(self):
        gl = pd.DataFrame([{"gl_id": "GL001", "Vendor_Normalized": "v", "amount": 1.0}])  # missing date+entity
        sub = _sub([_sub_row()])
        with pytest.raises(ValueError, match="GL pool missing required columns"):
            run_probabilistic_matching(gl, sub)

    def test_missing_sub_column_raises_value_error(self):
        gl = _gl([_gl_row()])
        sub = pd.DataFrame([{"subledger_id": "S1", "Vendor_Normalized": "v"}])  # missing columns
        with pytest.raises(ValueError, match="Sub pool missing required columns"):
            run_probabilistic_matching(gl, sub)


# ===========================================================================
# Result shape
# ===========================================================================

class TestResultShape:
    def test_user_status_is_pending(self):
        result = _run([_gl_row()], [_sub_row()])
        assert all(m.user_status == "pending" for m in result.matches)

    def test_override_flag_is_false(self):
        result = _run([_gl_row()], [_sub_row()])
        assert all(m.override_flag is False for m in result.matches)

    def test_component_scores_keys(self):
        result = _run([_gl_row()], [_sub_row()])
        expected = {"vendor_similarity", "amount_similarity", "date_similarity", "entity_similarity"}
        assert all(set(m.component_scores.keys()) == expected for m in result.matches)

    def test_grouping_type_values(self):
        result = _run([_gl_row()], [_sub_row()])
        valid = {"one_to_one", "many_to_one", "one_to_many"}
        assert all(m.grouping_type in valid for m in result.matches)

    def test_match_id_non_empty(self):
        result = _run([_gl_row()], [_sub_row()])
        assert all(len(m.match_id) > 0 for m in result.matches)

    def test_total_counts(self):
        result = _run(
            [_gl_row(gl_id="GL001"), _gl_row(gl_id="GL002", entity="CORP_X", vendor="x", amount=1.0)],
            [_sub_row(sub_id="SUB001")],
        )
        assert result.total_gl == 2
        assert result.total_sub == 1

    def test_matched_plus_residual_equals_total_gl(self):
        result = _run(
            [_gl_row(gl_id="GL001"), _gl_row(gl_id="GL002", entity="CORP_X", vendor="x", amount=1.0)],
            [_sub_row(sub_id="SUB001")],
        )
        assert result.matched_gl + len(result.residual_gl) == result.total_gl

    def test_matched_plus_residual_equals_total_sub(self):
        result = _run(
            [_gl_row(gl_id="GL001")],
            [_sub_row(sub_id="SUB001"), _sub_row(sub_id="SUB002", entity="CORP_X", vendor="x", amount=1.0)],
        )
        assert result.matched_sub + len(result.residual_sub) == result.total_sub

    def test_threshold_stored(self):
        result = _run([_gl_row()], [_sub_row()], threshold=0.75)
        assert result.threshold_used == 0.75

    def test_weights_stored(self):
        custom = {"vendor": 0.5, "amount": 0.3, "date": 0.2}
        result = _run([_gl_row()], [_sub_row()], weights=custom)
        assert result.weights_used == custom

    def test_to_match_list_serializable(self):
        result = _run([_gl_row()], [_sub_row()])
        for d in result.to_match_list():
            assert isinstance(d, dict)
            assert "match_id" in d
            assert "record_ids_A" in d
            assert "record_ids_B" in d
            assert "final_similarity" in d
            assert "component_scores" in d
            assert "grouping_type" in d
            assert "user_status" in d
            assert "override_flag" in d
