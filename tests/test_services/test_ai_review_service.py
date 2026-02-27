"""
Unit tests for src/services/ai_review_service.py

Phase 6A residual contract (different from Phase 5A):
  - AI phase is ADVISORY — residual pool is NOT consumed during Phase 6.
  - Accepted records must be REMOVED from residual (they are now matched).
  - Rejected / pending records remain in the residual unchanged.

Tests every explicit requirement:

  [Classification]
  - Accepted match: user_status == "accepted"
  - Rejected match: user_status == "rejected"
  - No-decision match: user_status unchanged ("pending")

  [Bucket routing]
  - Accepted match appears in accepted_matches (→ final)
  - Accepted match NOT in remaining_ai_suggested
  - Rejected match appears in rejected_matches
  - Rejected match NOT in remaining_ai_suggested
  - No-decision match in remaining_ai_suggested
  - Mixed decisions routed correctly

  [Counts]
  - accepted_count equals number of accepted decisions
  - rejected_count equals number of rejected decisions
  - remaining_ai_suggested() length == pending count

  [Residual pool — accepted removal]
  - Accepted GL IDs are removed from residual
  - Accepted Sub IDs are removed from residual
  - Only accepted records removed; other residual rows preserved

  [Residual pool — rejected / pending unchanged]
  - Rejected records remain in residual (they were already there)
  - Pending records remain in residual (they were already there)
  - All-rejected: residual unchanged
  - Empty decisions: residual unchanged

  [Edge cases]
  - Empty decision list → all pending, residual unchanged
  - All accepted → none remaining in ai_suggested, accepted records removed from residual
  - All rejected → none remaining in ai_suggested, residual unchanged
  - Unknown match_id in decisions raises ValueError
  - Empty ai_matches + empty decisions → result is empty, no error

  [remaining_ai_suggested()]
  - Returns pending matches only
  - Accepted + rejected matches not in remaining
"""

import pandas as pd
import pytest

from src.services.ai_review_service import AIReviewResult, process_ai_review


# ---------------------------------------------------------------------------
# Test fixtures
# ---------------------------------------------------------------------------

def _make_ai_match(match_id: str, gl_id: str, sub_id: str) -> dict:
    return {
        "match_id":            match_id,
        "record_ids_A":        [gl_id],
        "record_ids_B":        [sub_id],
        "ai_confidence_score": 0.85,
        "materiality":         100.0,
        "supporting_features": {"vendor_similarity": 1.0, "amount_diff": 0.0,
                                 "amount_diff_pct": 0.0, "date_diff_days": 0, "entity": "CORP"},
        "reasoning_narrative": "Test narrative.",
        "grouping_type":       "one_to_one",
        "user_status":         "pending",
        "override_flag":       False,
    }


def _make_residual_gl(*gl_ids) -> pd.DataFrame:
    """Build a residual GL DataFrame — simulates records still in residual after AI phase."""
    rows = [
        {
            "gl_id":            gid,
            "Vendor_Normalized": "test vendor",
            "amount":           100.0,
            "transaction_date": "2024-01-01",
            "entity":           "CORP",
        }
        for gid in gl_ids
    ]
    return pd.DataFrame(rows)


def _make_residual_sub(*sub_ids) -> pd.DataFrame:
    """Build a residual Sub DataFrame — simulates records still in residual after AI phase."""
    rows = [
        {
            "subledger_id":     sid,
            "Vendor_Normalized": "test vendor",
            "amount":           100.0,
            "transaction_date": "2024-01-01",
            "entity":           "CORP",
        }
        for sid in sub_ids
    ]
    return pd.DataFrame(rows)


def _empty() -> pd.DataFrame:
    return pd.DataFrame()


def _run(decisions, ai_matches, residual_gl=None, residual_sub=None) -> AIReviewResult:
    """Run process_ai_review with sensible defaults."""
    if residual_gl is None:
        residual_gl = _empty()
    if residual_sub is None:
        residual_sub = _empty()
    return process_ai_review(
        decisions=            decisions,
        ai_matches=           ai_matches,
        current_residual_gl=  residual_gl,
        current_residual_sub= residual_sub,
        clean_gl=             _empty(),   # unused in Phase 6A
        clean_sub=            _empty(),   # unused in Phase 6A
    )


# ---------------------------------------------------------------------------
# Shared test objects
# ---------------------------------------------------------------------------

_M1 = _make_ai_match("M1", "GL001", "SUB001")
_M2 = _make_ai_match("M2", "GL002", "SUB002")
_M3 = _make_ai_match("M3", "GL003", "SUB003")

# Residual containing all three AI-suggested records (typical Phase 6A entry state)
_RESIDUAL_GL  = _make_residual_gl("GL001", "GL002", "GL003")
_RESIDUAL_SUB = _make_residual_sub("SUB001", "SUB002", "SUB003")


# ===========================================================================
# Classification
# ===========================================================================

class TestClassification:
    def test_accepted_user_status(self):
        result = _run(
            [{"match_id": "M1", "decision": "accepted"}],
            [_M1],
            residual_gl=_RESIDUAL_GL, residual_sub=_RESIDUAL_SUB,
        )
        assert result.accepted_matches[0]["user_status"] == "accepted"

    def test_rejected_user_status(self):
        result = _run(
            [{"match_id": "M1", "decision": "rejected"}],
            [_M1],
            residual_gl=_RESIDUAL_GL, residual_sub=_RESIDUAL_SUB,
        )
        assert result.rejected_matches[0]["user_status"] == "rejected"

    def test_no_decision_user_status_unchanged(self):
        result = _run([], [_M1], residual_gl=_RESIDUAL_GL, residual_sub=_RESIDUAL_SUB)
        assert result.pending_matches[0]["user_status"] == "pending"


# ===========================================================================
# Bucket routing
# ===========================================================================

class TestBucketRouting:
    def test_accepted_in_accepted_matches(self):
        result = _run(
            [{"match_id": "M1", "decision": "accepted"}], [_M1],
            residual_gl=_RESIDUAL_GL, residual_sub=_RESIDUAL_SUB,
        )
        assert any(m["match_id"] == "M1" for m in result.accepted_matches)

    def test_accepted_not_in_remaining_ai_suggested(self):
        result = _run(
            [{"match_id": "M1", "decision": "accepted"}], [_M1],
            residual_gl=_RESIDUAL_GL, residual_sub=_RESIDUAL_SUB,
        )
        assert not any(m["match_id"] == "M1" for m in result.remaining_ai_suggested())

    def test_rejected_in_rejected_matches(self):
        result = _run(
            [{"match_id": "M1", "decision": "rejected"}], [_M1],
            residual_gl=_RESIDUAL_GL, residual_sub=_RESIDUAL_SUB,
        )
        assert any(m["match_id"] == "M1" for m in result.rejected_matches)

    def test_rejected_not_in_remaining_ai_suggested(self):
        result = _run(
            [{"match_id": "M1", "decision": "rejected"}], [_M1],
            residual_gl=_RESIDUAL_GL, residual_sub=_RESIDUAL_SUB,
        )
        assert not any(m["match_id"] == "M1" for m in result.remaining_ai_suggested())

    def test_no_decision_in_remaining_ai_suggested(self):
        result = _run([], [_M1], residual_gl=_RESIDUAL_GL, residual_sub=_RESIDUAL_SUB)
        assert any(m["match_id"] == "M1" for m in result.remaining_ai_suggested())

    def test_mixed_decisions_routing(self):
        result = _run(
            [
                {"match_id": "M1", "decision": "accepted"},
                {"match_id": "M2", "decision": "rejected"},
            ],
            [_M1, _M2, _M3],
            residual_gl=_RESIDUAL_GL, residual_sub=_RESIDUAL_SUB,
        )
        assert len(result.accepted_matches) == 1
        assert len(result.rejected_matches) == 1
        assert len(result.pending_matches)  == 1
        assert result.accepted_matches[0]["match_id"] == "M1"
        assert result.rejected_matches[0]["match_id"] == "M2"
        assert result.pending_matches[0]["match_id"]  == "M3"


# ===========================================================================
# Counts
# ===========================================================================

class TestCounts:
    def test_accepted_count_all_accepted(self):
        result = _run(
            [{"match_id": "M1", "decision": "accepted"},
             {"match_id": "M2", "decision": "accepted"}],
            [_M1, _M2],
            residual_gl=_RESIDUAL_GL, residual_sub=_RESIDUAL_SUB,
        )
        assert result.accepted_count == 2

    def test_rejected_count_all_rejected(self):
        result = _run(
            [{"match_id": "M1", "decision": "rejected"},
             {"match_id": "M2", "decision": "rejected"}],
            [_M1, _M2],
            residual_gl=_RESIDUAL_GL, residual_sub=_RESIDUAL_SUB,
        )
        assert result.rejected_count == 2

    def test_accepted_count_zero_when_none_accepted(self):
        result = _run([], [_M1], residual_gl=_RESIDUAL_GL, residual_sub=_RESIDUAL_SUB)
        assert result.accepted_count == 0

    def test_rejected_count_zero_when_none_rejected(self):
        result = _run(
            [{"match_id": "M1", "decision": "accepted"}], [_M1],
            residual_gl=_RESIDUAL_GL, residual_sub=_RESIDUAL_SUB,
        )
        assert result.rejected_count == 0

    def test_remaining_length_equals_pending_count(self):
        result = _run(
            [{"match_id": "M1", "decision": "accepted"}],
            [_M1, _M2, _M3],
            residual_gl=_RESIDUAL_GL, residual_sub=_RESIDUAL_SUB,
        )
        assert len(result.remaining_ai_suggested()) == 2


# ===========================================================================
# Residual pool — accepted removal
# ===========================================================================

class TestAcceptedRemoval:
    def test_accepted_gl_id_removed_from_residual(self):
        """Accepting a match removes its GL record from the residual pool."""
        result = _run(
            [{"match_id": "M1", "decision": "accepted"}],
            [_M1],
            residual_gl=_RESIDUAL_GL, residual_sub=_RESIDUAL_SUB,
        )
        residual_ids = set(result.updated_residual_gl["gl_id"].astype(str))
        assert "GL001" not in residual_ids

    def test_accepted_sub_id_removed_from_residual(self):
        """Accepting a match removes its Sub record from the residual pool."""
        result = _run(
            [{"match_id": "M1", "decision": "accepted"}],
            [_M1],
            residual_gl=_RESIDUAL_GL, residual_sub=_RESIDUAL_SUB,
        )
        residual_ids = set(result.updated_residual_sub["subledger_id"].astype(str))
        assert "SUB001" not in residual_ids

    def test_only_accepted_records_removed_not_others(self):
        """Other residual records are not affected by an accepted decision."""
        result = _run(
            [{"match_id": "M1", "decision": "accepted"}],
            [_M1, _M2, _M3],
            residual_gl=_RESIDUAL_GL, residual_sub=_RESIDUAL_SUB,
        )
        residual_ids = set(result.updated_residual_gl["gl_id"].astype(str))
        assert "GL002" in residual_ids
        assert "GL003" in residual_ids

    def test_all_accepted_residual_empty(self):
        """Accepting all AI suggestions empties the residual (if all were in it)."""
        result = _run(
            [{"match_id": "M1", "decision": "accepted"},
             {"match_id": "M2", "decision": "accepted"},
             {"match_id": "M3", "decision": "accepted"}],
            [_M1, _M2, _M3],
            residual_gl=_RESIDUAL_GL, residual_sub=_RESIDUAL_SUB,
        )
        assert result.updated_residual_gl.empty or len(result.updated_residual_gl) == 0

    def test_accept_with_empty_residual_no_error(self):
        """Accepting when residual is empty raises no error (nothing to remove)."""
        result = _run(
            [{"match_id": "M1", "decision": "accepted"}],
            [_M1],
        )
        assert result.accepted_count == 1


# ===========================================================================
# Residual pool — rejected / pending unchanged
# ===========================================================================

class TestResidualUnchanged:
    def test_rejected_records_remain_in_residual(self):
        """Rejected records stay in the residual (they were already there)."""
        result = _run(
            [{"match_id": "M1", "decision": "rejected"}],
            [_M1],
            residual_gl=_RESIDUAL_GL, residual_sub=_RESIDUAL_SUB,
        )
        residual_ids = set(result.updated_residual_gl["gl_id"].astype(str))
        assert "GL001" in residual_ids

    def test_all_rejected_residual_unchanged(self):
        """All-rejected: residual pool is unchanged."""
        result = _run(
            [{"match_id": "M1", "decision": "rejected"},
             {"match_id": "M2", "decision": "rejected"}],
            [_M1, _M2],
            residual_gl=_RESIDUAL_GL, residual_sub=_RESIDUAL_SUB,
        )
        # All three original records still present (M3 is pending too)
        residual_ids = set(result.updated_residual_gl["gl_id"].astype(str))
        assert {"GL001", "GL002", "GL003"}.issubset(residual_ids)

    def test_empty_decisions_residual_unchanged(self):
        """No decisions → residual pool is unchanged."""
        result = _run([], [_M1, _M2], residual_gl=_RESIDUAL_GL, residual_sub=_RESIDUAL_SUB)
        residual_ids = set(result.updated_residual_gl["gl_id"].astype(str))
        assert {"GL001", "GL002", "GL003"}.issubset(residual_ids)

    def test_pending_sub_records_remain_in_residual(self):
        result = _run([], [_M1], residual_gl=_RESIDUAL_GL, residual_sub=_RESIDUAL_SUB)
        residual_ids = set(result.updated_residual_sub["subledger_id"].astype(str))
        assert "SUB001" in residual_ids


# ===========================================================================
# Edge cases
# ===========================================================================

class TestEdgeCases:
    def test_empty_decisions_all_pending(self):
        result = _run([], [_M1, _M2], residual_gl=_RESIDUAL_GL, residual_sub=_RESIDUAL_SUB)
        assert result.accepted_count == 0
        assert result.rejected_count == 0
        assert len(result.remaining_ai_suggested()) == 2

    def test_all_accepted_none_remaining(self):
        result = _run(
            [{"match_id": "M1", "decision": "accepted"},
             {"match_id": "M2", "decision": "accepted"}],
            [_M1, _M2],
            residual_gl=_RESIDUAL_GL, residual_sub=_RESIDUAL_SUB,
        )
        assert len(result.remaining_ai_suggested()) == 0

    def test_all_rejected_none_remaining(self):
        result = _run(
            [{"match_id": "M1", "decision": "rejected"},
             {"match_id": "M2", "decision": "rejected"}],
            [_M1, _M2],
            residual_gl=_RESIDUAL_GL, residual_sub=_RESIDUAL_SUB,
        )
        assert len(result.remaining_ai_suggested()) == 0

    def test_unknown_match_id_raises_value_error(self):
        with pytest.raises(ValueError, match="Unknown match_id"):
            _run(
                [{"match_id": "DOES_NOT_EXIST", "decision": "accepted"}],
                [_M1],
                residual_gl=_RESIDUAL_GL, residual_sub=_RESIDUAL_SUB,
            )

    def test_empty_ai_matches_empty_decisions_no_error(self):
        result = _run([], [])
        assert result.accepted_count == 0
        assert result.rejected_count == 0
        assert len(result.remaining_ai_suggested()) == 0


# ===========================================================================
# remaining_ai_suggested
# ===========================================================================

class TestRemainingAiSuggested:
    def test_returns_pending_only(self):
        result = _run(
            [{"match_id": "M1", "decision": "accepted"},
             {"match_id": "M2", "decision": "rejected"}],
            [_M1, _M2, _M3],
            residual_gl=_RESIDUAL_GL, residual_sub=_RESIDUAL_SUB,
        )
        remaining_ids = {m["match_id"] for m in result.remaining_ai_suggested()}
        assert remaining_ids == {"M3"}

    def test_accepted_not_in_remaining(self):
        result = _run(
            [{"match_id": "M1", "decision": "accepted"}],
            [_M1, _M2],
            residual_gl=_RESIDUAL_GL, residual_sub=_RESIDUAL_SUB,
        )
        remaining_ids = {m["match_id"] for m in result.remaining_ai_suggested()}
        assert "M1" not in remaining_ids

    def test_rejected_not_in_remaining(self):
        result = _run(
            [{"match_id": "M1", "decision": "rejected"}],
            [_M1, _M2],
            residual_gl=_RESIDUAL_GL, residual_sub=_RESIDUAL_SUB,
        )
        remaining_ids = {m["match_id"] for m in result.remaining_ai_suggested()}
        assert "M1" not in remaining_ids
