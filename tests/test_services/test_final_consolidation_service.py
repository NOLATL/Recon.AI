"""
Unit tests for src/services/final_consolidation_service.py

Tests every explicit requirement:

  [Layer inclusion]
  - All deterministic matches included (regardless of user_status)
  - Only accepted probabilistic matches included (user_status == "accepted")
  - Pending probabilistic matches excluded
  - AI final matches included as-is (already accepted by Phase 6A)

  [all_matches ordering]
  - Deterministic matches appear before probabilistic in all_matches
  - Probabilistic accepted matches appear before AI matches
  - Match IDs from all layers present in all_matches

  [Counts — deterministic]
  - deterministic_match_count == len(det_matches input)
  - Zero when det_matches is empty

  [Counts — probabilistic]
  - probabilistic_match_count == count of accepted prob matches only
  - Pending prob matches not counted
  - Rejected prob matches not counted (they were moved to rejected bucket by Phase 5A)
  - Zero when no accepted prob matches

  [Counts — AI]
  - ai_match_count == len(ai_final input)
  - Zero when ai_final is empty

  [Counts — total]
  - total_match_count == det + accepted_prob + ai
  - Zero when all inputs empty

  [Counts — residual]
  - residual_gl_count == len(residual_gl DataFrame)
  - residual_sub_count == len(residual_sub DataFrame)
  - Zero when residual DataFrames are empty or None

  [Counts — rejected]
  - rejected_count == len(rejected input list)
  - Zero when rejected is empty

  [Override count]
  - override_count == number of matches with override_flag=True in all_matches
  - Zero in typical case (override_flag=False on all matches in v1)

  [Edge cases]
  - All inputs empty → zero counts, empty all_matches, no error
  - Only deterministic → total == det count
  - Only accepted prob → total == accepted prob count
  - Only AI final → total == ai count
  - Mixed: partial prob acceptance + partial AI
"""

import pandas as pd
import pytest

from src.services.final_consolidation_service import (
    FinalConsolidationResult,
    run_final_consolidation,
)


# ---------------------------------------------------------------------------
# Match dict builders
# ---------------------------------------------------------------------------

def _det(match_id: str, gl_id: str, sub_id: str) -> dict:
    return {
        "match_id":             match_id,
        "record_ids_A":         [gl_id],
        "record_ids_B":         [sub_id],
        "scenario_id":          1,
        "scenario_description": "Exact match",
        "confidence_score":     1.0,
        "grouping_type":        "one_to_one",
        "user_status":          "auto_confirmed",
        "override_flag":        False,
    }


def _prob(match_id: str, gl_id: str, sub_id: str, user_status: str = "accepted") -> dict:
    return {
        "match_id":         match_id,
        "record_ids_A":     [gl_id],
        "record_ids_B":     [sub_id],
        "final_similarity": 0.92,
        "component_scores": {"vendor_similarity": 1.0, "amount_similarity": 0.98,
                              "date_similarity": 1.0, "entity_similarity": 1.0},
        "grouping_type":    "one_to_one",
        "user_status":      user_status,
        "override_flag":    False,
    }


def _ai(match_id: str, gl_id: str, sub_id: str, user_status: str = "accepted") -> dict:
    return {
        "match_id":            match_id,
        "record_ids_A":        [gl_id],
        "record_ids_B":        [sub_id],
        "ai_confidence_score": 0.90,
        "materiality":         1000.0,
        "supporting_features": {"vendor_similarity": 1.0, "amount_diff": 400.0,
                                 "amount_diff_pct": 28.6, "date_diff_days": 0, "entity": "AI_E"},
        "reasoning_narrative": "Test narrative.",
        "grouping_type":       "one_to_one",
        "user_status":         user_status,
        "override_flag":       False,
    }


def _gl_residual(*ids) -> pd.DataFrame:
    return pd.DataFrame([{"gl_id": i, "amount": 100.0} for i in ids])


def _sub_residual(*ids) -> pd.DataFrame:
    return pd.DataFrame([{"subledger_id": i, "amount": 100.0} for i in ids])


def _run(det=None, prob=None, ai_final=None, rejected=None,
         residual_gl=None, residual_sub=None) -> FinalConsolidationResult:
    return run_final_consolidation(
        det_matches=  det      or [],
        prob_matches= prob     or [],
        ai_final=     ai_final or [],
        rejected=     rejected or [],
        residual_gl=  residual_gl  if residual_gl  is not None else pd.DataFrame(),
        residual_sub= residual_sub if residual_sub is not None else pd.DataFrame(),
    )


# ===========================================================================
# Layer inclusion
# ===========================================================================

class TestLayerInclusion:
    def test_all_deterministic_included(self):
        result = _run(det=[_det("D1", "GL1", "S1"), _det("D2", "GL2", "S2")])
        assert result.deterministic_match_count == 2

    def test_only_accepted_prob_included(self):
        result = _run(prob=[
            _prob("P1", "GL3", "S3", "accepted"),
            _prob("P2", "GL4", "S4", "pending"),
        ])
        assert result.probabilistic_match_count == 1

    def test_pending_prob_excluded(self):
        result = _run(prob=[_prob("P1", "GL3", "S3", "pending")])
        assert result.probabilistic_match_count == 0

    def test_ai_final_included_as_is(self):
        result = _run(ai_final=[_ai("A1", "GL5", "S5")])
        assert result.ai_match_count == 1

    def test_all_layers_combined(self):
        result = _run(
            det=[_det("D1", "GL1", "S1")],
            prob=[_prob("P1", "GL3", "S3", "accepted"), _prob("P2", "GL4", "S4", "pending")],
            ai_final=[_ai("A1", "GL5", "S5")],
        )
        assert result.deterministic_match_count == 1
        assert result.probabilistic_match_count == 1
        assert result.ai_match_count == 1
        assert result.total_match_count == 3


# ===========================================================================
# all_matches ordering and content
# ===========================================================================

class TestAllMatchesContent:
    def test_det_matches_in_all_matches(self):
        result = _run(det=[_det("D1", "GL1", "S1")])
        ids = {m["match_id"] for m in result.all_matches}
        assert "D1" in ids

    def test_accepted_prob_in_all_matches(self):
        result = _run(prob=[_prob("P1", "GL3", "S3", "accepted")])
        ids = {m["match_id"] for m in result.all_matches}
        assert "P1" in ids

    def test_pending_prob_not_in_all_matches(self):
        result = _run(prob=[_prob("P1", "GL3", "S3", "pending")])
        ids = {m["match_id"] for m in result.all_matches}
        assert "P1" not in ids

    def test_ai_final_in_all_matches(self):
        result = _run(ai_final=[_ai("A1", "GL5", "S5")])
        ids = {m["match_id"] for m in result.all_matches}
        assert "A1" in ids

    def test_ordering_det_before_prob_before_ai(self):
        result = _run(
            det=[_det("D1", "GL1", "S1")],
            prob=[_prob("P1", "GL3", "S3", "accepted")],
            ai_final=[_ai("A1", "GL5", "S5")],
        )
        all_ids = [m["match_id"] for m in result.all_matches]
        assert all_ids.index("D1") < all_ids.index("P1")
        assert all_ids.index("P1") < all_ids.index("A1")

    def test_all_matches_len_equals_total_count(self):
        result = _run(
            det=[_det("D1", "GL1", "S1")],
            prob=[_prob("P1", "GL3", "S3", "accepted")],
            ai_final=[_ai("A1", "GL5", "S5")],
        )
        assert len(result.all_matches) == result.total_match_count


# ===========================================================================
# Counts — deterministic
# ===========================================================================

class TestDeterministicCounts:
    def test_count_equals_input_length(self):
        result = _run(det=[_det("D1", "GL1", "S1"), _det("D2", "GL2", "S2")])
        assert result.deterministic_match_count == 2

    def test_count_zero_when_empty(self):
        result = _run()
        assert result.deterministic_match_count == 0


# ===========================================================================
# Counts — probabilistic
# ===========================================================================

class TestProbabilisticCounts:
    def test_count_accepted_only(self):
        result = _run(prob=[
            _prob("P1", "GL1", "S1", "accepted"),
            _prob("P2", "GL2", "S2", "accepted"),
            _prob("P3", "GL3", "S3", "pending"),
        ])
        assert result.probabilistic_match_count == 2

    def test_count_zero_when_all_pending(self):
        result = _run(prob=[_prob("P1", "GL1", "S1", "pending")])
        assert result.probabilistic_match_count == 0

    def test_count_zero_when_empty(self):
        result = _run()
        assert result.probabilistic_match_count == 0


# ===========================================================================
# Counts — AI
# ===========================================================================

class TestAICounts:
    def test_count_equals_ai_final_length(self):
        result = _run(ai_final=[_ai("A1", "GL5", "S5"), _ai("A2", "GL6", "S6")])
        assert result.ai_match_count == 2

    def test_count_zero_when_empty(self):
        result = _run()
        assert result.ai_match_count == 0


# ===========================================================================
# Counts — total
# ===========================================================================

class TestTotalCount:
    def test_total_is_sum_of_layers(self):
        result = _run(
            det=[_det("D1", "GL1", "S1")],
            prob=[_prob("P1", "GL3", "S3", "accepted")],
            ai_final=[_ai("A1", "GL5", "S5")],
        )
        assert result.total_match_count == 3

    def test_total_excludes_pending_prob(self):
        result = _run(
            det=[_det("D1", "GL1", "S1")],
            prob=[_prob("P1", "GL3", "S3", "accepted"),
                  _prob("P2", "GL4", "S4", "pending")],
        )
        assert result.total_match_count == 2

    def test_total_zero_when_all_empty(self):
        result = _run()
        assert result.total_match_count == 0


# ===========================================================================
# Counts — residual
# ===========================================================================

class TestResidualCounts:
    def test_residual_gl_count(self):
        result = _run(residual_gl=_gl_residual("GL_R1", "GL_R2"))
        assert result.residual_gl_count == 2

    def test_residual_sub_count(self):
        result = _run(residual_sub=_sub_residual("S_R1", "S_R2", "S_R3"))
        assert result.residual_sub_count == 3

    def test_residual_counts_zero_when_empty(self):
        result = _run()
        assert result.residual_gl_count == 0
        assert result.residual_sub_count == 0

    def test_residual_counts_zero_when_none(self):
        result = run_final_consolidation([], [], [], [], None, None)
        assert result.residual_gl_count == 0
        assert result.residual_sub_count == 0


# ===========================================================================
# Counts — rejected
# ===========================================================================

class TestRejectedCount:
    def test_rejected_count(self):
        rejected = [_prob("P_R1", "GL1", "S1", "rejected"),
                    _ai("A_R1", "GL2", "S2", "rejected")]
        result = _run(rejected=rejected)
        assert result.rejected_count == 2

    def test_rejected_count_zero(self):
        result = _run()
        assert result.rejected_count == 0


# ===========================================================================
# Override count
# ===========================================================================

class TestOverrideCount:
    def test_override_count_zero_in_typical_case(self):
        result = _run(
            det=[_det("D1", "GL1", "S1")],
            prob=[_prob("P1", "GL3", "S3", "accepted")],
            ai_final=[_ai("A1", "GL5", "S5")],
        )
        assert result.override_count == 0

    def test_override_count_counts_override_flag_true(self):
        override_match = {**_det("D1", "GL1", "S1"), "override_flag": True}
        result = _run(det=[override_match, _det("D2", "GL2", "S2")])
        assert result.override_count == 1

    def test_override_count_only_in_accepted_matches(self):
        # override in pending prob → should NOT be counted (pending not in all_matches)
        override_pending = {**_prob("P1", "GL1", "S1", "pending"), "override_flag": True}
        result = _run(prob=[override_pending])
        assert result.override_count == 0


# ===========================================================================
# Edge cases
# ===========================================================================

class TestEdgeCases:
    def test_all_empty_no_error(self):
        result = _run()
        assert result.total_match_count == 0
        assert result.all_matches == []
        assert result.residual_gl_count == 0
        assert result.residual_sub_count == 0
        assert result.rejected_count == 0
        assert result.override_count == 0

    def test_only_deterministic(self):
        result = _run(det=[_det("D1", "GL1", "S1"), _det("D2", "GL2", "S2")])
        assert result.total_match_count == 2
        assert result.probabilistic_match_count == 0
        assert result.ai_match_count == 0

    def test_only_accepted_prob(self):
        result = _run(prob=[_prob("P1", "GL1", "S1", "accepted")])
        assert result.total_match_count == 1
        assert result.deterministic_match_count == 0
        assert result.ai_match_count == 0

    def test_only_ai_final(self):
        result = _run(ai_final=[_ai("A1", "GL5", "S5")])
        assert result.total_match_count == 1
        assert result.deterministic_match_count == 0
        assert result.probabilistic_match_count == 0

    def test_mixed_prob_acceptance(self):
        """Partial acceptance: only accepted prob counted, pending excluded."""
        result = _run(prob=[
            _prob("P1", "GL1", "S1", "accepted"),
            _prob("P2", "GL2", "S2", "pending"),
            _prob("P3", "GL3", "S3", "accepted"),
        ])
        assert result.probabilistic_match_count == 2
        assert result.total_match_count == 2
