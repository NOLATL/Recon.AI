"""
AI advisory layer — thin wrapper.

Authority: ADVISORY ONLY — suggestions are never applied automatically.
           Human review is required before any AI suggestion becomes a match.
Activation: PROBABILISTIC_REVIEW_COMPLETE → AI_SUGGESTED

All matching logic lives in src/services/ai_matching_service.py.
This module exists only for legacy compatibility and is NOT called by the
Phase 6 route handler (ai_routes.py calls the service directly).
"""

import pandas as pd

import src.core.runtime_manager as rm
from src.core.state_machine import ReconciliationState
from src.services.ai_matching_service import (
    DEFAULT_AI_MODEL,
    DEFAULT_PROMPT_VERSION,
    run_ai_matching,
)


def run(session_id: str, triggered_by: str = "system") -> dict:
    """
    Generate AI-assisted suggestions for remaining unmatched records.

    Expected pre-condition:  current_state == PROBABILISTIC_REVIEW_COMPLETE
    Post-condition:          current_state == AI_SUGGESTED
                             runtime["matching"]["ai_suggested"] populated

    Advisory only — residual pool is never mutated.

    Returns a summary dict with suggestion counts and model metadata.
    """
    rm.assert_not_in_review(session_id)

    runtime  = rm.get_runtime(session_id)
    config   = runtime["config"]
    pool     = runtime.get("residual_pool", {})

    gl_pool  = pool.get("gl",        pd.DataFrame())
    sub_pool = pool.get("subledger",  pd.DataFrame())

    ai_model       = config.get("ai_model") or DEFAULT_AI_MODEL
    prompt_version = DEFAULT_PROMPT_VERSION

    result = run_ai_matching(
        residual_gl=    gl_pool,
        residual_sub=   sub_pool,
        ai_model=       ai_model,
        prompt_version= prompt_version,
    )

    rm.write_matching_results(session_id, "ai_suggested", result.to_suggestion_list())
    rm.write_ai_suggested_meta(session_id, {
        "model_used":       result.model_used,
        "prompt_version":   result.prompt_version,
        "suggestion_count": len(result.suggestions),
    })

    rm.advance_state(session_id, ReconciliationState.AI_SUGGESTED, triggered_by)

    return {
        "layer":            "ai_advisory",
        "suggestion_count": len(result.suggestions),
        "model_used":       result.model_used,
        "new_state":        rm.get_current_state(session_id).value,
    }
