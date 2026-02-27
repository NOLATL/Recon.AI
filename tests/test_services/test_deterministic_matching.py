"""
Unit tests for src/services/deterministic_matching.py

Tests every explicit requirement:

  [Scenario 1 — Strict 1:1]
  - Exact match on Vendor_Normalized, amount, date, entity produces a match
  - Match has scenario_id=1, confidence_score=1.0, grouping_type="one_to_one"
  - Matched records are removed from residual

  [Scenario 2 — Vendor + Amount + Date tolerance]
  - Match on Vendor_Normalized + amount with date within 60 days
  - Date exactly 60 days apart → match (boundary inclusive)
  - Date 61 days apart → no match
  - Match has scenario_id=2, confidence_score=0.95
  - Records not consumed by scenario 1 are available for scenario 2

  [Scenario 3 — Amount + Entity + Date tolerance]
  - Match on amount + entity with date within 60 days
  - Match has scenario_id=3, confidence_score=0.85
  - Records not consumed by scenarios 1–2 are available for scenario 3

  [Scenario 4 — Deterministic grouping]
  - N:1: two GL rows summing to one Sub amount → match with grouping_type="many_to_one"
  - 1:N: one GL row whose amount equals sum of two Sub rows → grouping_type="one_to_many"
  - Match has scenario_id=4, confidence_score=0.75
  - Records consumed in N:1 are not reused in 1:N

  [Ordered execution / pool removal]
  - A record matched in scenario 1 is NOT in the residual pool
  - A record matched in scenario 1 is NOT available for scenario 2 or 3
  - Unmatched records appear in residual_gl / residual_sub

  [Edge cases]
  - Empty GL and/or Sub DataFrames → no matches, empty residuals
  - No match at all → all records in residual
  - Missing required column raises ValueError

  [Result shape]
  - Each MatchRecord has all required fields
  - scenario_counts keys are {1, 2, 3, 4}
  - total_gl / total_sub equal input lengths
  - matched_gl + len(residual_gl) == total_gl
"""

import pandas as pd
import pytest

from src.services.deterministic_matching import (
    DATE_TOLERANCE_DAYS,
    DeterministicResult,
    MatchRecord,
    run_deterministic_matching,
)


# ---------------------------------------------------------------------------
# DataFrame builders
# ---------------------------------------------------------------------------

def _gl(rows: list) -> pd.DataFrame:
    """Build a minimal GL DataFrame from a list of row dicts."""
    return pd.DataFrame(rows)


def _sub(rows: list) -> pd.DataFrame:
    """Build a minimal Sub DataFrame from a list of row dicts."""
    return pd.DataFrame(rows)


def _gl_row(
    gl_id="GL001",
    vendor="vendor a",
    amount=100.00,
    date="2024-01-15",
    entity="CORP",
) -> dict:
    return {
        "gl_id": gl_id,
        "Vendor_Normalized": vendor,
        "amount": amount,
        "transaction_date": date,
        "entity": entity,
    }


def _sub_row(
    sub_id="SUB001",
    vendor="vendor a",
    amount=100.00,
    date="2024-01-15",
    entity="CORP",
) -> dict:
    return {
        "subledger_id": sub_id,
        "Vendor_Normalized": vendor,
        "amount": amount,
        "transaction_date": date,
        "entity": entity,
    }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _run(gl_rows, sub_rows) -> DeterministicResult:
    return run_deterministic_matching(_gl(gl_rows), _sub(sub_rows))


def _matches_by_scenario(result: DeterministicResult) -> dict:
    """Group matches by scenario_id for easy assertion."""
    groups: dict = {1: [], 2: [], 3: [], 4: []}
    for m in result.matches:
        groups[m.scenario_id].append(m)
    return groups


# ===========================================================================
# Scenario 1 — Strict 1:1
# ===========================================================================

class TestScenario1:
    def test_exact_match_produces_match(self):
        result = _run([_gl_row()], [_sub_row()])
        assert len(result.matches) == 1

    def test_scenario_id_is_1(self):
        result = _run([_gl_row()], [_sub_row()])
        assert result.matches[0].scenario_id == 1

    def test_confidence_score_is_1(self):
        result = _run([_gl_row()], [_sub_row()])
        assert result.matches[0].confidence_score == 1.00

    def test_grouping_type_is_one_to_one(self):
        result = _run([_gl_row()], [_sub_row()])
        assert result.matches[0].grouping_type == "one_to_one"

    def test_record_ids_correct(self):
        result = _run([_gl_row()], [_sub_row()])
        m = result.matches[0]
        assert m.record_ids_A == ["GL001"]
        assert m.record_ids_B == ["SUB001"]

    def test_matched_records_removed_from_residual_gl(self):
        result = _run([_gl_row()], [_sub_row()])
        assert len(result.residual_gl) == 0

    def test_matched_records_removed_from_residual_sub(self):
        result = _run([_gl_row()], [_sub_row()])
        assert len(result.residual_sub) == 0

    def test_different_vendor_no_match(self):
        gl  = [_gl_row(vendor="vendor a")]
        sub = [_sub_row(vendor="vendor b")]
        result = _run(gl, sub)
        s1 = _matches_by_scenario(result)[1]
        assert len(s1) == 0

    def test_different_amount_no_match(self):
        gl  = [_gl_row(amount=100.00)]
        sub = [_sub_row(amount=200.00)]
        result = _run(gl, sub)
        s1 = _matches_by_scenario(result)[1]
        assert len(s1) == 0

    def test_different_date_no_scenario1_match(self):
        gl  = [_gl_row(date="2024-01-15")]
        sub = [_sub_row(date="2024-03-20")]
        result = _run(gl, sub)
        s1 = _matches_by_scenario(result)[1]
        assert len(s1) == 0

    def test_different_entity_no_match(self):
        gl  = [_gl_row(entity="CORP_A")]
        sub = [_sub_row(entity="CORP_B")]
        result = _run(gl, sub)
        s1 = _matches_by_scenario(result)[1]
        assert len(s1) == 0

    def test_amount_rounded_match(self):
        """0.105 rounds to 0.11; both sides equal → match."""
        gl  = [_gl_row(amount=0.105)]
        sub = [_sub_row(amount=0.105)]
        result = _run(gl, sub)
        assert len(result.matches) == 1

    def test_user_status_is_auto_confirmed(self):
        result = _run([_gl_row()], [_sub_row()])
        assert result.matches[0].user_status == "auto_confirmed"

    def test_override_flag_is_false(self):
        result = _run([_gl_row()], [_sub_row()])
        assert result.matches[0].override_flag is False


# ===========================================================================
# Scenario 2 — Vendor + Amount + Date tolerance ±60 days
# ===========================================================================

class TestScenario2:
    """
    Use matching vendor/amount but different date to avoid scenario 1;
    different entity to avoid scenario 3.
    """

    def test_date_within_tolerance_produces_match(self):
        gl  = [_gl_row(date="2024-01-15", entity="A")]
        sub = [_sub_row(date="2024-02-20", entity="B")]   # 36 days diff, diff entity
        result = _run(gl, sub)
        s2 = _matches_by_scenario(result)[2]
        assert len(s2) == 1

    def test_scenario_id_is_2(self):
        gl  = [_gl_row(date="2024-01-15", entity="A")]
        sub = [_sub_row(date="2024-02-20", entity="B")]
        result = _run(gl, sub)
        assert _matches_by_scenario(result)[2][0].scenario_id == 2

    def test_confidence_score_is_0_95(self):
        gl  = [_gl_row(date="2024-01-15", entity="A")]
        sub = [_sub_row(date="2024-02-20", entity="B")]
        result = _run(gl, sub)
        assert _matches_by_scenario(result)[2][0].confidence_score == 0.95

    def test_boundary_60_days_matches(self):
        """Exactly 60 days difference — should match."""
        gl  = [_gl_row(date="2024-01-01", entity="A")]
        sub = [_sub_row(date="2024-03-01", entity="B")]   # 60 days diff
        result = _run(gl, sub)
        s2 = _matches_by_scenario(result)[2]
        assert len(s2) == 1

    def test_boundary_61_days_no_match(self):
        """61 days difference — should NOT match."""
        gl  = [_gl_row(date="2024-01-01", entity="A")]
        sub = [_sub_row(date="2024-03-03", entity="B")]   # 62 days diff
        result = _run(gl, sub)
        s2 = _matches_by_scenario(result)[2]
        assert len(s2) == 0

    def test_different_vendor_no_match_in_scenario2(self):
        gl  = [_gl_row(vendor="vendor a", date="2024-01-15", entity="A")]
        sub = [_sub_row(vendor="vendor b", date="2024-01-20", entity="B")]
        result = _run(gl, sub)
        s2 = _matches_by_scenario(result)[2]
        assert len(s2) == 0

    def test_scenario1_records_not_available_for_scenario2(self):
        """Record matched in scenario 1 must not appear in scenario 2 matches."""
        # Two GL rows; one matches scenario 1, one should match scenario 2
        gl = [
            _gl_row(gl_id="GL001", date="2024-01-15", entity="CORP"),  # exact match S1
            _gl_row(gl_id="GL002", date="2024-01-15", entity="A"),      # date-tolerance S2
        ]
        sub = [
            _sub_row(sub_id="SUB001", date="2024-01-15", entity="CORP"),  # S1 match
            _sub_row(sub_id="SUB002", date="2024-02-10", entity="B"),     # S2 match
        ]
        result = _run(gl, sub)
        s1_gl_ids = {m.record_ids_A[0] for m in _matches_by_scenario(result)[1]}
        s2_gl_ids = {m.record_ids_A[0] for m in _matches_by_scenario(result)[2]}
        assert s1_gl_ids.isdisjoint(s2_gl_ids)


# ===========================================================================
# Scenario 3 — Amount + Entity + Date tolerance ±60 days
# ===========================================================================

class TestScenario3:
    """
    Use different vendors so scenarios 1 & 2 don't fire; same entity for S3.
    """

    def test_amount_entity_date_tolerance_produces_match(self):
        gl  = [_gl_row(vendor="vendor x", date="2024-01-15")]
        sub = [_sub_row(vendor="vendor y", date="2024-02-01")]   # same entity, within 60d
        result = _run(gl, sub)
        s3 = _matches_by_scenario(result)[3]
        assert len(s3) == 1

    def test_scenario_id_is_3(self):
        gl  = [_gl_row(vendor="vendor x", date="2024-01-15")]
        sub = [_sub_row(vendor="vendor y", date="2024-02-01")]
        result = _run(gl, sub)
        assert _matches_by_scenario(result)[3][0].scenario_id == 3

    def test_confidence_score_is_0_85(self):
        gl  = [_gl_row(vendor="vendor x", date="2024-01-15")]
        sub = [_sub_row(vendor="vendor y", date="2024-02-01")]
        result = _run(gl, sub)
        assert _matches_by_scenario(result)[3][0].confidence_score == 0.85

    def test_different_entity_no_match_in_scenario3(self):
        gl  = [_gl_row(vendor="vendor x", entity="A")]
        sub = [_sub_row(vendor="vendor y", entity="B")]
        result = _run(gl, sub)
        s3 = _matches_by_scenario(result)[3]
        assert len(s3) == 0

    def test_boundary_60_days_matches_in_scenario3(self):
        gl  = [_gl_row(vendor="vendor x", date="2024-01-01")]
        sub = [_sub_row(vendor="vendor y", date="2024-03-01")]   # 60 days
        result = _run(gl, sub)
        s3 = _matches_by_scenario(result)[3]
        assert len(s3) == 1

    def test_prior_scenario_records_not_reused_in_scenario3(self):
        """Record matched in S1 or S2 must not appear in S3 matches."""
        gl = [
            _gl_row(gl_id="GL001", vendor="vendor a", date="2024-01-15", entity="CORP"),
            _gl_row(gl_id="GL002", vendor="vendor z", date="2024-01-15", entity="CORP"),
        ]
        sub = [
            _sub_row(sub_id="SUB001", vendor="vendor a", date="2024-01-15", entity="CORP"),
            _sub_row(sub_id="SUB002", vendor="vendor w", date="2024-01-20", entity="CORP"),
        ]
        result = _run(gl, sub)
        s1_gl = {m.record_ids_A[0] for m in _matches_by_scenario(result)[1]}
        s3_gl = {m.record_ids_A[0] for m in _matches_by_scenario(result)[3]}
        assert s1_gl.isdisjoint(s3_gl)


# ===========================================================================
# Scenario 4 — Deterministic grouping
# ===========================================================================

class TestScenario4:

    def test_n_to_1_match(self):
        """Two GL rows sum to one Sub amount → many_to_one match."""
        gl = [
            _gl_row(gl_id="GL001", vendor="vendor x", amount=60.00, date="2099-01-01"),
            _gl_row(gl_id="GL002", vendor="vendor y", amount=40.00, date="2099-01-01"),
        ]
        sub = [
            _sub_row(sub_id="SUB001", vendor="vendor z", amount=100.00, date="2099-01-01"),
        ]
        result = _run(gl, sub)
        s4 = _matches_by_scenario(result)[4]
        assert len(s4) == 1
        assert s4[0].grouping_type == "many_to_one"
        assert sorted(s4[0].record_ids_A) == ["GL001", "GL002"]
        assert s4[0].record_ids_B == ["SUB001"]

    def test_n_to_1_scenario_id_is_4(self):
        gl = [
            _gl_row(gl_id="GL001", vendor="vx", amount=60.00, date="2099-01-01"),
            _gl_row(gl_id="GL002", vendor="vy", amount=40.00, date="2099-01-01"),
        ]
        sub = [_sub_row(sub_id="SUB001", vendor="vz", amount=100.00, date="2099-01-01")]
        result = _run(gl, sub)
        assert _matches_by_scenario(result)[4][0].scenario_id == 4

    def test_n_to_1_confidence_score_is_0_75(self):
        gl = [
            _gl_row(gl_id="GL001", vendor="vx", amount=60.00, date="2099-01-01"),
            _gl_row(gl_id="GL002", vendor="vy", amount=40.00, date="2099-01-01"),
        ]
        sub = [_sub_row(sub_id="SUB001", vendor="vz", amount=100.00, date="2099-01-01")]
        result = _run(gl, sub)
        assert _matches_by_scenario(result)[4][0].confidence_score == 0.75

    def test_1_to_n_match(self):
        """One GL row equals sum of two Sub rows → one_to_many match."""
        gl = [
            _gl_row(gl_id="GL001", vendor="vendor x", amount=100.00, date="2099-01-01"),
        ]
        sub = [
            _sub_row(sub_id="SUB001", vendor="vendor y", amount=60.00, date="2099-01-01"),
            _sub_row(sub_id="SUB002", vendor="vendor z", amount=40.00, date="2099-01-01"),
        ]
        result = _run(gl, sub)
        s4 = _matches_by_scenario(result)[4]
        assert len(s4) == 1
        assert s4[0].grouping_type == "one_to_many"
        assert s4[0].record_ids_A == ["GL001"]
        assert sorted(s4[0].record_ids_B) == ["SUB001", "SUB002"]

    def test_entity_boundary_enforced(self):
        """GL and Sub in different entities must NOT be grouped."""
        gl = [
            _gl_row(gl_id="GL001", vendor="vx", amount=60.00, date="2099-01-01", entity="A"),
            _gl_row(gl_id="GL002", vendor="vy", amount=40.00, date="2099-01-01", entity="A"),
        ]
        sub = [
            _sub_row(sub_id="SUB001", vendor="vz", amount=100.00, date="2099-01-01", entity="B"),
        ]
        result = _run(gl, sub)
        s4 = _matches_by_scenario(result)[4]
        assert len(s4) == 0

    def test_n_to_1_records_removed_from_residual(self):
        gl = [
            _gl_row(gl_id="GL001", vendor="vx", amount=60.00, date="2099-01-01"),
            _gl_row(gl_id="GL002", vendor="vy", amount=40.00, date="2099-01-01"),
        ]
        sub = [_sub_row(sub_id="SUB001", vendor="vz", amount=100.00, date="2099-01-01")]
        result = _run(gl, sub)
        assert len(result.residual_gl) == 0
        assert len(result.residual_sub) == 0

    def test_no_double_use_of_records_between_n1_and_1n(self):
        """
        In N:1 phase, GL001+GL002 are matched to SUB001.
        They must not be reused in the 1:N phase.
        """
        gl = [
            _gl_row(gl_id="GL001", vendor="vx", amount=60.00, date="2099-01-01"),
            _gl_row(gl_id="GL002", vendor="vy", amount=40.00, date="2099-01-01"),
            _gl_row(gl_id="GL003", vendor="vq", amount=100.00, date="2099-01-01"),
        ]
        sub = [
            _sub_row(sub_id="SUB001", vendor="vz", amount=100.00, date="2099-01-01"),
            _sub_row(sub_id="SUB002", vendor="vw", amount=60.00, date="2099-01-01"),
            _sub_row(sub_id="SUB003", vendor="vv", amount=40.00, date="2099-01-01"),
        ]
        result = _run(gl, sub)
        # GL001+GL002 matched to SUB001 (N:1); GL003 matched to SUB002+SUB003 (1:N)
        used_gl = [rid for m in result.matches for rid in m.record_ids_A]
        used_sub = [rid for m in result.matches for rid in m.record_ids_B]
        # No duplicates
        assert len(used_gl) == len(set(used_gl))
        assert len(used_sub) == len(set(used_sub))


# ===========================================================================
# Ordered execution / pool removal
# ===========================================================================

class TestOrderedExecution:

    def test_s1_match_not_in_residual(self):
        result = _run([_gl_row()], [_sub_row()])
        assert "GL001" not in result.residual_gl["gl_id"].tolist()
        assert "SUB001" not in result.residual_sub["subledger_id"].tolist()

    def test_unmatched_appear_in_residual_gl(self):
        gl = [_gl_row(gl_id="GL001"), _gl_row(gl_id="GL002", vendor="no_match")]
        sub = [_sub_row()]
        result = _run(gl, sub)
        assert "GL002" in result.residual_gl["gl_id"].tolist()

    def test_unmatched_appear_in_residual_sub(self):
        gl = [_gl_row()]
        sub = [_sub_row(sub_id="SUB001"), _sub_row(sub_id="SUB002", vendor="no_match")]
        result = _run(gl, sub)
        assert "SUB002" in result.residual_sub["subledger_id"].tolist()

    def test_scenario_counts_sum_to_match_count(self):
        gl = [_gl_row(gl_id="GL001"), _gl_row(gl_id="GL002", vendor="vendor x")]
        sub = [_sub_row(), _sub_row(sub_id="SUB002", vendor="vendor y")]
        result = _run(gl, sub)
        total_from_counts = sum(result.scenario_counts.values())
        assert total_from_counts == len(result.matches)

    def test_matched_gl_plus_residual_gl_equals_total_gl(self):
        gl = [_gl_row(gl_id="GL001"), _gl_row(gl_id="GL002", vendor="unmatched")]
        sub = [_sub_row()]
        result = _run(gl, sub)
        assert result.matched_gl + len(result.residual_gl) == result.total_gl

    def test_matched_sub_plus_residual_sub_equals_total_sub(self):
        gl = [_gl_row()]
        sub = [_sub_row(sub_id="SUB001"), _sub_row(sub_id="SUB002", vendor="unmatched")]
        result = _run(gl, sub)
        assert result.matched_sub + len(result.residual_sub) == result.total_sub


# ===========================================================================
# Edge cases
# ===========================================================================

class TestEdgeCases:

    def test_empty_gl_no_matches(self):
        result = _run([], [_sub_row()])
        assert len(result.matches) == 0

    def test_empty_sub_no_matches(self):
        result = _run([_gl_row()], [])
        assert len(result.matches) == 0

    def test_empty_both_no_matches(self):
        result = _run([], [])
        assert len(result.matches) == 0

    def test_empty_gl_residual_gl_is_empty(self):
        result = _run([], [_sub_row()])
        assert len(result.residual_gl) == 0

    def test_empty_sub_residual_sub_is_empty(self):
        result = _run([_gl_row()], [])
        assert len(result.residual_sub) == 0

    def test_no_match_all_records_in_residual(self):
        gl  = [_gl_row(vendor="aaa", amount=1.00, date="2020-01-01")]
        sub = [_sub_row(vendor="bbb", amount=9.00, date="2020-01-01")]
        result = _run(gl, sub)
        assert len(result.matches) == 0
        assert len(result.residual_gl) == 1
        assert len(result.residual_sub) == 1

    def test_missing_gl_id_column_raises_value_error(self):
        gl = pd.DataFrame([{"Vendor_Normalized": "x", "amount": 1, "transaction_date": "2024-01-01", "entity": "A"}])
        sub = pd.DataFrame([{"subledger_id": "S1", "Vendor_Normalized": "x", "amount": 1, "transaction_date": "2024-01-01", "entity": "A"}])
        with pytest.raises(ValueError, match="gl_id"):
            run_deterministic_matching(gl, sub)

    def test_missing_subledger_id_column_raises_value_error(self):
        gl = pd.DataFrame([{"gl_id": "G1", "Vendor_Normalized": "x", "amount": 1, "transaction_date": "2024-01-01", "entity": "A"}])
        sub = pd.DataFrame([{"Vendor_Normalized": "x", "amount": 1, "transaction_date": "2024-01-01", "entity": "A"}])
        with pytest.raises(ValueError, match="subledger_id"):
            run_deterministic_matching(gl, sub)


# ===========================================================================
# Result shape
# ===========================================================================

class TestResultShape:

    def test_match_record_has_all_required_fields(self):
        result = _run([_gl_row()], [_sub_row()])
        m = result.matches[0]
        assert hasattr(m, "match_id")
        assert hasattr(m, "record_ids_A")
        assert hasattr(m, "record_ids_B")
        assert hasattr(m, "scenario_id")
        assert hasattr(m, "scenario_description")
        assert hasattr(m, "confidence_score")
        assert hasattr(m, "grouping_type")
        assert hasattr(m, "user_status")
        assert hasattr(m, "override_flag")

    def test_match_id_is_non_empty_string(self):
        result = _run([_gl_row()], [_sub_row()])
        assert isinstance(result.matches[0].match_id, str)
        assert len(result.matches[0].match_id) > 0

    def test_scenario_counts_has_all_four_keys(self):
        result = _run([_gl_row()], [_sub_row()])
        assert set(result.scenario_counts.keys()) == {1, 2, 3, 4}

    def test_total_gl_matches_input_length(self):
        gl = [_gl_row(gl_id=f"GL{i:03d}") for i in range(5)]
        sub = []
        result = _run(gl, sub)
        assert result.total_gl == 5

    def test_total_sub_matches_input_length(self):
        gl = []
        sub = [_sub_row(sub_id=f"SUB{i:03d}") for i in range(3)]
        result = _run(gl, sub)
        assert result.total_sub == 3

    def test_to_match_list_returns_list_of_dicts(self):
        result = _run([_gl_row()], [_sub_row()])
        lst = result.to_match_list()
        assert isinstance(lst, list)
        assert isinstance(lst[0], dict)

    def test_to_match_list_dict_has_required_keys(self):
        result = _run([_gl_row()], [_sub_row()])
        d = result.to_match_list()[0]
        for key in (
            "match_id", "record_ids_A", "record_ids_B",
            "scenario_id", "scenario_description",
            "confidence_score", "grouping_type",
            "user_status", "override_flag",
        ):
            assert key in d
