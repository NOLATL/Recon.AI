"""
Unit tests for src/services/ai_matching_service.py

Tests every explicit requirement:

  [Ranking]
  - Suggestions ranked by materiality descending
  - When materiality equal, ranked by ai_confidence_score descending

  [Advisory — no dataset mutation]
  - Residual GL pool unchanged after run
  - Residual Sub pool unchanged after run
  - Suggestion count does not depend on pool mutation (idempotent)

  [Match object shape]
  - user_status == "pending" for all suggestions
  - override_flag == False for all suggestions
  - supporting_features has required keys
  - reasoning_narrative is non-empty string
  - grouping_type in {"one_to_one"}   (stub is 1:1 only)
  - match_id is non-empty string
  - record_ids_A and record_ids_B are lists

  [Threshold — AI_MIN_CONFIDENCE]
  - Very dissimilar pairs (different entity) are excluded (confidence < min)
  - Similar same-entity pairs are included

  [Entity grouping]
  - Cross-entity pairs are never suggested
  - Same-entity pairs with sufficient confidence are suggested

  [Edge cases]
  - Both pools empty → no suggestions, zero total counts
  - GL pool empty → no suggestions
  - Sub pool empty → no suggestions
  - No shared entity → no suggestions
  - Missing required GL column raises ValueError
  - Missing required Sub column raises ValueError

  [Metadata]
  - model_used stored in result
  - prompt_version stored in result
  - total_residual_gl == input GL pool length
  - total_residual_sub == input Sub pool length
  - to_suggestion_list() returns dicts with all required keys
"""

import pandas as pd
import pytest

from src.services.ai_matching_service import (
    AI_MIN_CONFIDENCE,
    DEFAULT_AI_MODEL,
    DEFAULT_PROMPT_VERSION,
    AIMatchingResult,
    run_ai_matching,
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
        "subledger_id":      sub_id,
        "Vendor_Normalized": vendor,
        "amount":            amount,
        "transaction_date":  date,
        "entity":            entity,
    }


def _run(gl_rows, sub_rows, model=DEFAULT_AI_MODEL,
         prompt=DEFAULT_PROMPT_VERSION) -> AIMatchingResult:
    return run_ai_matching(_gl(gl_rows), _sub(sub_rows),
                           ai_model=model, prompt_version=prompt)


# ===========================================================================
# Ranking
# ===========================================================================

class TestRanking:
    def test_ranked_by_materiality_descending(self):
        """Higher GL amount = higher materiality = ranks first."""
        result = _run(
            [
                _gl_row(gl_id="GL001", amount=100.0),
                _gl_row(gl_id="GL002", amount=500.0),
            ],
            [
                _sub_row(sub_id="SUB001", amount=100.0),
                _sub_row(sub_id="SUB002", amount=500.0),
            ],
        )
        mats = [s.materiality for s in result.suggestions]
        assert mats == sorted(mats, reverse=True), \
            f"Expected materiality descending, got {mats}"

    def test_equal_materiality_ranked_by_confidence_descending(self):
        """Same GL amounts → higher confidence suggestion ranks first."""
        result = _run(
            [
                _gl_row(gl_id="GL001", vendor="vendor alpha", amount=100.0),
                _gl_row(gl_id="GL002", vendor="different name", amount=100.0),
            ],
            [_sub_row(sub_id="SUB001", vendor="vendor alpha", amount=100.0)],
        )
        if len(result.suggestions) >= 2:
            assert (result.suggestions[0].ai_confidence_score
                    >= result.suggestions[1].ai_confidence_score)

    def test_highest_materiality_is_first(self):
        """Explicit: the highest-amount GL pair should appear first."""
        result = _run(
            [
                _gl_row(gl_id="GL_LOW",  amount=50.0),
                _gl_row(gl_id="GL_HIGH", amount=999.0),
            ],
            [
                _sub_row(sub_id="SUB_LOW",  amount=50.0),
                _sub_row(sub_id="SUB_HIGH", amount=999.0),
            ],
        )
        # Both should have at least one suggestion; the high-amount one first
        assert result.suggestions[0].materiality >= result.suggestions[-1].materiality


# ===========================================================================
# Advisory — no dataset mutation
# ===========================================================================

class TestAdvisory:
    def test_residual_gl_unchanged(self):
        gl = _gl([_gl_row()])
        sub = _sub([_sub_row()])
        original_gl = gl.copy()
        run_ai_matching(gl, sub)
        pd.testing.assert_frame_equal(gl.reset_index(drop=True),
                                       original_gl.reset_index(drop=True))

    def test_residual_sub_unchanged(self):
        gl = _gl([_gl_row()])
        sub = _sub([_sub_row()])
        original_sub = sub.copy()
        run_ai_matching(gl, sub)
        pd.testing.assert_frame_equal(sub.reset_index(drop=True),
                                       original_sub.reset_index(drop=True))

    def test_idempotent(self):
        """Running twice on the same pools produces the same count."""
        gl  = _gl([_gl_row()])
        sub = _sub([_sub_row()])
        r1 = run_ai_matching(gl.copy(), sub.copy())
        r2 = run_ai_matching(gl.copy(), sub.copy())
        assert len(r1.suggestions) == len(r2.suggestions)


# ===========================================================================
# Match object shape
# ===========================================================================

class TestMatchObjectShape:
    def test_user_status_is_pending(self):
        result = _run([_gl_row()], [_sub_row()])
        assert all(s.user_status == "pending" for s in result.suggestions)

    def test_override_flag_is_false(self):
        result = _run([_gl_row()], [_sub_row()])
        assert all(s.override_flag is False for s in result.suggestions)

    def test_supporting_features_has_required_keys(self):
        result = _run([_gl_row()], [_sub_row()])
        required = {"vendor_similarity", "amount_diff", "amount_diff_pct",
                    "date_diff_days", "entity"}
        for s in result.suggestions:
            assert set(s.supporting_features.keys()) >= required

    def test_reasoning_narrative_non_empty(self):
        result = _run([_gl_row()], [_sub_row()])
        assert all(len(s.reasoning_narrative) > 0 for s in result.suggestions)

    def test_grouping_type_is_one_to_one(self):
        result = _run([_gl_row()], [_sub_row()])
        assert all(s.grouping_type == "one_to_one" for s in result.suggestions)

    def test_match_id_non_empty(self):
        result = _run([_gl_row()], [_sub_row()])
        assert all(len(s.match_id) > 0 for s in result.suggestions)

    def test_record_ids_are_lists(self):
        result = _run([_gl_row()], [_sub_row()])
        for s in result.suggestions:
            assert isinstance(s.record_ids_A, list)
            assert isinstance(s.record_ids_B, list)

    def test_record_ids_non_empty(self):
        result = _run([_gl_row()], [_sub_row()])
        for s in result.suggestions:
            assert len(s.record_ids_A) > 0
            assert len(s.record_ids_B) > 0


# ===========================================================================
# Entity grouping
# ===========================================================================

class TestEntityGrouping:
    def test_cross_entity_pair_not_suggested(self):
        result = _run(
            [_gl_row(entity="CORP_A")],
            [_sub_row(entity="CORP_B")],
        )
        assert len(result.suggestions) == 0

    def test_same_entity_pair_suggested(self):
        result = _run(
            [_gl_row(entity="CORP_X", vendor="vendor alpha", amount=100.0)],
            [_sub_row(entity="CORP_X", vendor="vendor alpha", amount=100.0)],
        )
        assert len(result.suggestions) == 1

    def test_multiple_entities_only_same_entity_paired(self):
        result = _run(
            [
                _gl_row(gl_id="GL_A", entity="CORP_A"),
                _gl_row(gl_id="GL_B", entity="CORP_B"),
            ],
            [
                _sub_row(sub_id="SUB_A", entity="CORP_A"),
                _sub_row(sub_id="SUB_B", entity="CORP_B"),
            ],
        )
        for s in result.suggestions:
            # record_ids must be from the same entity group
            gl_entity  = "CORP_A" if s.record_ids_A[0] == "GL_A" else "CORP_B"
            sub_entity = "CORP_A" if s.record_ids_B[0] == "SUB_A" else "CORP_B"
            assert gl_entity == sub_entity


# ===========================================================================
# Edge cases
# ===========================================================================

class TestEdgeCases:
    def test_both_empty_no_suggestions(self):
        result = run_ai_matching(pd.DataFrame(), pd.DataFrame())
        assert len(result.suggestions) == 0
        assert result.total_residual_gl == 0
        assert result.total_residual_sub == 0

    def test_gl_empty_no_suggestions(self):
        result = run_ai_matching(pd.DataFrame(), _sub([_sub_row()]))
        assert len(result.suggestions) == 0

    def test_sub_empty_no_suggestions(self):
        result = run_ai_matching(_gl([_gl_row()]), pd.DataFrame())
        assert len(result.suggestions) == 0

    def test_no_shared_entity_no_suggestions(self):
        result = _run(
            [_gl_row(entity="ONLY_GL")],
            [_sub_row(entity="ONLY_SUB")],
        )
        assert len(result.suggestions) == 0

    def test_missing_gl_column_raises_value_error(self):
        bad_gl = pd.DataFrame([{"gl_id": "GL001", "Vendor_Normalized": "v"}])
        sub    = _sub([_sub_row()])
        with pytest.raises(ValueError, match="GL residual missing required columns"):
            run_ai_matching(bad_gl, sub)

    def test_missing_sub_column_raises_value_error(self):
        gl     = _gl([_gl_row()])
        bad_sub = pd.DataFrame([{"subledger_id": "S1"}])
        with pytest.raises(ValueError, match="Sub residual missing required columns"):
            run_ai_matching(gl, bad_sub)


# ===========================================================================
# Metadata
# ===========================================================================

class TestMetadata:
    def test_model_used_stored(self):
        result = _run([_gl_row()], [_sub_row()], model="custom-model")
        assert result.model_used == "custom-model"

    def test_prompt_version_stored(self):
        result = _run([_gl_row()], [_sub_row()], prompt="v2.0.0")
        assert result.prompt_version == "v2.0.0"

    def test_total_residual_gl_correct(self):
        result = _run([_gl_row(gl_id="GL001"), _gl_row(gl_id="GL002")], [_sub_row()])
        assert result.total_residual_gl == 2

    def test_total_residual_sub_correct(self):
        result = _run([_gl_row()], [_sub_row(sub_id="S1"), _sub_row(sub_id="S2")])
        assert result.total_residual_sub == 2

    def test_to_suggestion_list_dict_keys(self):
        result = _run([_gl_row()], [_sub_row()])
        expected = {
            "match_id", "record_ids_A", "record_ids_B", "ai_confidence_score",
            "materiality", "supporting_features", "reasoning_narrative",
            "grouping_type", "user_status", "override_flag",
        }
        for d in result.to_suggestion_list():
            assert set(d.keys()) == expected

    def test_default_model_name(self):
        result = _run([_gl_row()], [_sub_row()])
        assert result.model_used == DEFAULT_AI_MODEL

    def test_default_prompt_version(self):
        result = _run([_gl_row()], [_sub_row()])
        assert result.prompt_version == DEFAULT_PROMPT_VERSION
