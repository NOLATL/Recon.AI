"""
Unit tests for src/services/ai_matching_service.py

All tests that exercise the matching pipeline mock OpenAIClient so no real
API calls are made. Tests that return early before reaching the LLM (empty pools,
column validation, cross-entity blocking) do not need a mock.

Patch path: src.services.ai_matching_service.OpenAIClient

Tests every explicit requirement:

  [Ranking]
  - Suggestions ranked by materiality descending
  - When materiality equal, ranked by ai_confidence_score descending
  - Highest-materiality suggestion appears first

  [Advisory — no dataset mutation]
  - Residual GL pool unchanged after run
  - Residual Sub pool unchanged after run
  - Suggestion count is stable given same mock response (idempotent)

  [Match object shape]
  - user_status == "pending" for all suggestions
  - override_flag == False for all suggestions
  - supporting_features has required keys
  - reasoning_narrative is non-empty string
  - grouping_type in valid set {"one_to_one", "many_to_one", "one_to_many", "many_to_many"}
  - match_id is non-empty string
  - record_ids_A and record_ids_B are non-empty lists

  [Entity grouping]
  - Cross-entity pairs are never suggested (no entity intersection → no LLM call)
  - Same-entity pairs with sufficient confidence are suggested
  - Multiple entities: only same-entity records paired

  [Edge cases]
  - Both pools empty → no suggestions, zero total counts
  - GL pool empty → no suggestions
  - Sub pool empty → no suggestions
  - No shared entity → no suggestions (no LLM call needed)
  - Missing required GL column raises ValueError
  - Missing required Sub column raises ValueError

  [Metadata]
  - model_used stored in result
  - prompt_version stored in result
  - total_residual_gl == input GL pool length
  - total_residual_sub == input Sub pool length
  - to_suggestion_list() returns dicts with all required keys
  - default model name matches DEFAULT_AI_MODEL constant
  - default prompt version matches DEFAULT_PROMPT_VERSION constant

  [Validation / deduplication]
  - Suggestion confidence below AI_MIN_CONFIDENCE is discarded
  - A record ID cannot appear in two suggestions
  - LLM returning a non-existent ID is silently discarded
"""

import pandas as pd
import pytest
from unittest.mock import patch, MagicMock

from src.services.ai_matching_service import (
    AI_MIN_CONFIDENCE,
    DEFAULT_AI_MODEL,
    DEFAULT_PROMPT_VERSION,
    AIMatchingResult,
    run_ai_matching,
)

# ---------------------------------------------------------------------------
# Patch target
# ---------------------------------------------------------------------------

_PATCH = "src.services.ai_matching_service.OpenAIClient"


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
        "gl_id":             gl_id,
        "Vendor_Normalized": vendor,
        "amount":            amount,
        "transaction_date":  date,
        "entity":            entity,
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


# ---------------------------------------------------------------------------
# Mock helpers
# ---------------------------------------------------------------------------

def _mock_client(matches: list):
    """
    Return a mock OpenAIClient instance whose generate_json() returns the
    given matches list wrapped in {"matches": [...]}.
    """
    inst = MagicMock()
    inst.generate_json.return_value = {"matches": matches}
    return inst


def _one_to_one_match(gl_id="GL001", sub_id="SUB001",
                      confidence=0.85, reasoning="Test match."):
    return {
        "gl_ids":     [gl_id],
        "sub_ids":    [sub_id],
        "confidence": confidence,
        "reasoning":  reasoning,
    }


# ===========================================================================
# Ranking
# ===========================================================================

class TestRanking:
    def test_ranked_by_materiality_descending(self):
        """Higher GL amount → higher materiality → ranks first."""
        with patch(_PATCH) as mock_cls:
            mock_cls.return_value = _mock_client([
                _one_to_one_match("GL001", "SUB001", confidence=0.80),
                _one_to_one_match("GL002", "SUB002", confidence=0.80),
            ])
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
        assert mats == sorted(mats, reverse=True)

    def test_equal_materiality_ranked_by_confidence_descending(self):
        """Same materiality → higher confidence ranks first."""
        # Mock returns lower-confidence match first; service must reorder.
        with patch(_PATCH) as mock_cls:
            mock_cls.return_value = _mock_client([
                _one_to_one_match("GL002", "SUB002", confidence=0.70),
                _one_to_one_match("GL001", "SUB001", confidence=0.90),
            ])
            result = _run(
                [
                    _gl_row(gl_id="GL001", vendor="vendor alpha", amount=100.0),
                    _gl_row(gl_id="GL002", vendor="vendor alpha", amount=100.0),
                ],
                [
                    _sub_row(sub_id="SUB001", vendor="vendor alpha", amount=100.0),
                    _sub_row(sub_id="SUB002", vendor="vendor alpha", amount=100.0),
                ],
            )
        assert len(result.suggestions) == 2
        assert (result.suggestions[0].ai_confidence_score
                >= result.suggestions[1].ai_confidence_score)

    def test_highest_materiality_is_first(self):
        """Explicit: highest-amount pair must appear first."""
        with patch(_PATCH) as mock_cls:
            mock_cls.return_value = _mock_client([
                _one_to_one_match("GL_LOW",  "SUB_LOW",  confidence=0.85),
                _one_to_one_match("GL_HIGH", "SUB_HIGH", confidence=0.85),
            ])
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
        assert result.suggestions[0].materiality >= result.suggestions[-1].materiality


# ===========================================================================
# Advisory — no dataset mutation
# ===========================================================================

class TestAdvisory:
    def test_residual_gl_unchanged(self):
        gl  = _gl([_gl_row()])
        sub = _sub([_sub_row()])
        original_gl = gl.copy()
        with patch(_PATCH) as mock_cls:
            mock_cls.return_value = _mock_client([_one_to_one_match()])
            run_ai_matching(gl, sub)
        pd.testing.assert_frame_equal(gl.reset_index(drop=True),
                                      original_gl.reset_index(drop=True))

    def test_residual_sub_unchanged(self):
        gl  = _gl([_gl_row()])
        sub = _sub([_sub_row()])
        original_sub = sub.copy()
        with patch(_PATCH) as mock_cls:
            mock_cls.return_value = _mock_client([_one_to_one_match()])
            run_ai_matching(gl, sub)
        pd.testing.assert_frame_equal(sub.reset_index(drop=True),
                                      original_sub.reset_index(drop=True))

    def test_idempotent(self):
        """Same mock response → same suggestion count on two runs."""
        gl  = _gl([_gl_row()])
        sub = _sub([_sub_row()])
        with patch(_PATCH) as mock_cls:
            mock_cls.return_value = _mock_client([_one_to_one_match()])
            r1 = run_ai_matching(gl.copy(), sub.copy())
            r2 = run_ai_matching(gl.copy(), sub.copy())
        assert len(r1.suggestions) == len(r2.suggestions)


# ===========================================================================
# Match object shape
# ===========================================================================

class TestMatchObjectShape:
    def _get_result(self):
        with patch(_PATCH) as mock_cls:
            mock_cls.return_value = _mock_client([_one_to_one_match()])
            return _run([_gl_row()], [_sub_row()])

    def test_user_status_is_pending(self):
        result = self._get_result()
        assert all(s.user_status == "pending" for s in result.suggestions)

    def test_override_flag_is_false(self):
        result = self._get_result()
        assert all(s.override_flag is False for s in result.suggestions)

    def test_supporting_features_has_required_keys(self):
        result = self._get_result()
        required = {"vendor_similarity", "amount_diff", "amount_diff_pct",
                    "date_diff_days", "entity"}
        for s in result.suggestions:
            assert set(s.supporting_features.keys()) >= required

    def test_reasoning_narrative_non_empty(self):
        result = self._get_result()
        assert all(len(s.reasoning_narrative) > 0 for s in result.suggestions)

    def test_grouping_type_valid(self):
        result = self._get_result()
        valid = {"one_to_one", "many_to_one", "one_to_many", "many_to_many"}
        assert all(s.grouping_type in valid for s in result.suggestions)

    def test_grouping_type_one_to_one_for_single_pair(self):
        """1 GL + 1 Sub returned by LLM → grouping_type == 'one_to_one'."""
        result = self._get_result()
        assert all(s.grouping_type == "one_to_one" for s in result.suggestions)

    def test_match_id_non_empty(self):
        result = self._get_result()
        assert all(len(s.match_id) > 0 for s in result.suggestions)

    def test_record_ids_are_lists(self):
        result = self._get_result()
        for s in result.suggestions:
            assert isinstance(s.record_ids_A, list)
            assert isinstance(s.record_ids_B, list)

    def test_record_ids_non_empty(self):
        result = self._get_result()
        for s in result.suggestions:
            assert len(s.record_ids_A) > 0
            assert len(s.record_ids_B) > 0

    def test_n_to_1_grouping_type(self):
        """Two GL + one Sub returned by LLM → grouping_type == 'many_to_one'."""
        with patch(_PATCH) as mock_cls:
            mock_cls.return_value = _mock_client([
                {
                    "gl_ids":     ["GL001", "GL002"],
                    "sub_ids":    ["SUB001"],
                    "confidence": 0.80,
                    "reasoning":  "Two GL lines sum to one Sub.",
                }
            ])
            result = _run(
                [
                    _gl_row(gl_id="GL001", amount=60.0),
                    _gl_row(gl_id="GL002", amount=40.0),
                ],
                [_sub_row(sub_id="SUB001", amount=100.0)],
            )
        assert len(result.suggestions) == 1
        assert result.suggestions[0].grouping_type == "many_to_one"

    def test_1_to_n_grouping_type(self):
        """One GL + two Sub returned by LLM → grouping_type == 'one_to_many'."""
        with patch(_PATCH) as mock_cls:
            mock_cls.return_value = _mock_client([
                {
                    "gl_ids":     ["GL001"],
                    "sub_ids":    ["SUB001", "SUB002"],
                    "confidence": 0.80,
                    "reasoning":  "One GL line split into two Sub entries.",
                }
            ])
            result = _run(
                [_gl_row(gl_id="GL001", amount=100.0)],
                [
                    _sub_row(sub_id="SUB001", amount=60.0),
                    _sub_row(sub_id="SUB002", amount=40.0),
                ],
            )
        assert len(result.suggestions) == 1
        assert result.suggestions[0].grouping_type == "one_to_many"


# ===========================================================================
# Entity grouping
# ===========================================================================

class TestEntityGrouping:
    def test_cross_entity_pair_not_suggested(self):
        """No entity intersection → no LLM call → no suggestions."""
        result = _run(
            [_gl_row(entity="CORP_A")],
            [_sub_row(entity="CORP_B")],
        )
        assert len(result.suggestions) == 0

    def test_same_entity_pair_suggested(self):
        with patch(_PATCH) as mock_cls:
            mock_cls.return_value = _mock_client([_one_to_one_match()])
            result = _run(
                [_gl_row(entity="CORP_X", vendor="vendor alpha", amount=100.0)],
                [_sub_row(entity="CORP_X", vendor="vendor alpha", amount=100.0)],
            )
        assert len(result.suggestions) == 1

    def test_multiple_entities_only_same_entity_paired(self):
        """CORP_A records must only be matched with CORP_A records."""
        with patch(_PATCH) as mock_cls:
            # First call: (CORP_A, vendor alpha) → GL_A + SUB_A
            # Second call: (CORP_B, vendor alpha) → GL_B + SUB_B
            mock_cls.return_value.generate_json.side_effect = [
                {"matches": [{"gl_ids": ["GL_A"], "sub_ids": ["SUB_A"],
                               "confidence": 0.85, "reasoning": "CORP_A."}]},
                {"matches": [{"gl_ids": ["GL_B"], "sub_ids": ["SUB_B"],
                               "confidence": 0.85, "reasoning": "CORP_B."}]},
            ]
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
        gl      = _gl([_gl_row()])
        bad_sub = pd.DataFrame([{"subledger_id": "S1"}])
        with pytest.raises(ValueError, match="Sub residual missing required columns"):
            run_ai_matching(gl, bad_sub)


# ===========================================================================
# Validation / deduplication
# ===========================================================================

class TestValidation:
    def test_low_confidence_suggestion_discarded(self):
        """LLM returns confidence below AI_MIN_CONFIDENCE → discarded."""
        with patch(_PATCH) as mock_cls:
            mock_cls.return_value = _mock_client([
                _one_to_one_match(confidence=AI_MIN_CONFIDENCE - 0.01)
            ])
            result = _run([_gl_row()], [_sub_row()])
        assert len(result.suggestions) == 0

    def test_confidence_at_minimum_accepted(self):
        """Confidence exactly at AI_MIN_CONFIDENCE → accepted (inclusive boundary)."""
        with patch(_PATCH) as mock_cls:
            mock_cls.return_value = _mock_client([
                _one_to_one_match(confidence=AI_MIN_CONFIDENCE)
            ])
            result = _run([_gl_row()], [_sub_row()])
        assert len(result.suggestions) == 1

    def test_nonexistent_gl_id_discarded(self):
        """LLM returns a GL ID not in the pool → suggestion silently dropped."""
        with patch(_PATCH) as mock_cls:
            mock_cls.return_value = _mock_client([
                _one_to_one_match(gl_id="PHANTOM_GL", sub_id="SUB001")
            ])
            result = _run([_gl_row(gl_id="GL001")], [_sub_row(sub_id="SUB001")])
        assert len(result.suggestions) == 0

    def test_nonexistent_sub_id_discarded(self):
        """LLM returns a Sub ID not in the pool → suggestion silently dropped."""
        with patch(_PATCH) as mock_cls:
            mock_cls.return_value = _mock_client([
                _one_to_one_match(gl_id="GL001", sub_id="PHANTOM_SUB")
            ])
            result = _run([_gl_row(gl_id="GL001")], [_sub_row(sub_id="SUB001")])
        assert len(result.suggestions) == 0

    def test_duplicate_record_id_not_in_two_matches(self):
        """LLM tries to use GL001 in two matches → second one discarded."""
        with patch(_PATCH) as mock_cls:
            mock_cls.return_value = _mock_client([
                _one_to_one_match("GL001", "SUB001", confidence=0.90),
                _one_to_one_match("GL001", "SUB002", confidence=0.85),  # duplicate GL001
            ])
            result = _run(
                [_gl_row(gl_id="GL001")],
                [
                    _sub_row(sub_id="SUB001"),
                    _sub_row(sub_id="SUB002"),
                ],
            )
        assert len(result.suggestions) == 1
        assert result.suggestions[0].record_ids_A == ["GL001"]
        assert result.suggestions[0].record_ids_B == ["SUB001"]

    def test_llm_failure_returns_no_suggestions(self):
        """LLM raises an exception → no suggestions, no crash."""
        with patch(_PATCH) as mock_cls:
            mock_cls.return_value.generate_json.side_effect = RuntimeError("API timeout")
            result = _run([_gl_row()], [_sub_row()])
        assert len(result.suggestions) == 0


# ===========================================================================
# Metadata
# ===========================================================================

class TestMetadata:
    def test_model_used_stored(self):
        with patch(_PATCH) as mock_cls:
            mock_cls.return_value = _mock_client([])
            result = _run([_gl_row()], [_sub_row()], model="custom-model")
        assert result.model_used == "custom-model"

    def test_prompt_version_stored(self):
        with patch(_PATCH) as mock_cls:
            mock_cls.return_value = _mock_client([])
            result = _run([_gl_row()], [_sub_row()], prompt="v3.0.0")
        assert result.prompt_version == "v3.0.0"

    def test_total_residual_gl_correct(self):
        with patch(_PATCH) as mock_cls:
            mock_cls.return_value = _mock_client([])
            result = _run([_gl_row(gl_id="GL001"), _gl_row(gl_id="GL002")], [_sub_row()])
        assert result.total_residual_gl == 2

    def test_total_residual_sub_correct(self):
        with patch(_PATCH) as mock_cls:
            mock_cls.return_value = _mock_client([])
            result = _run([_gl_row()], [_sub_row(sub_id="S1"), _sub_row(sub_id="S2")])
        assert result.total_residual_sub == 2

    def test_to_suggestion_list_dict_keys(self):
        with patch(_PATCH) as mock_cls:
            mock_cls.return_value = _mock_client([_one_to_one_match()])
            result = _run([_gl_row()], [_sub_row()])
        expected = {
            "match_id", "record_ids_A", "record_ids_B", "ai_confidence_score",
            "materiality", "supporting_features", "reasoning_narrative",
            "grouping_type", "user_status", "override_flag",
        }
        for d in result.to_suggestion_list():
            assert set(d.keys()) == expected

    def test_default_model_name(self):
        with patch(_PATCH) as mock_cls:
            mock_cls.return_value = _mock_client([])
            result = _run([_gl_row()], [_sub_row()])
        assert result.model_used == DEFAULT_AI_MODEL

    def test_default_prompt_version(self):
        with patch(_PATCH) as mock_cls:
            mock_cls.return_value = _mock_client([])
            result = _run([_gl_row()], [_sub_row()])
        assert result.prompt_version == DEFAULT_PROMPT_VERSION
