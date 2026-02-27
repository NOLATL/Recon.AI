"""
Probabilistic matching layer — thin wrapper.

Authority: ADDITIVE — results augment deterministic matches; never override them.
Activation: DETERMINISTIC_REVIEW_COMPLETE → PROBABILISTIC_COMPLETE

All matching logic lives in src/services/probabilistic_matching.py.
This module exists only for legacy compatibility and is NOT called by the
Phase 5 route handler (probabilistic_routes.py calls the service directly).
"""

import src.core.runtime_manager as rm
from src.core.state_machine import ReconciliationState
from src.services.probabilistic_matching import (
    DEFAULT_THRESHOLD,
    DEFAULT_WEIGHTS,
    run_probabilistic_matching,
)


def run(session_id: str, triggered_by: str = "system") -> dict:
    """
    Execute probabilistic (fuzzy) matching on the residual pool.

    Expected pre-condition:  current_state == DETERMINISTIC_REVIEW_COMPLETE
    Post-condition:          current_state == PROBABILISTIC_COMPLETE
                             runtime["matching"]["probabilistic"] populated

    Returns a summary dict with match count and threshold used.
    """
    rm.assert_not_in_review(session_id)

    runtime   = rm.get_runtime(session_id)
    config    = runtime["config"]
    pool      = runtime.get("residual_pool", {})
    gl_pool   = pool.get("gl")
    sub_pool  = pool.get("subledger")

    threshold   = config.get("threshold") or DEFAULT_THRESHOLD
    raw_weights = config.get("weights") or {}
    weights     = {**DEFAULT_WEIGHTS, **raw_weights}

    result = run_probabilistic_matching(
        gl_pool=gl_pool,
        sub_pool=sub_pool,
        threshold=threshold,
        weights=weights,
    )

    rm.write_matching_results(session_id, "probabilistic", result.to_match_list())
    rm.write_residual_pool(session_id, {
        "gl":        result.residual_gl,
        "subledger": result.residual_sub,
    })
    rm.write_probabilistic(session_id, {
        "threshold_used": result.threshold_used,
        "weights_used":   result.weights_used,
        "match_count":    len(result.matches),
    })

    rm.advance_state(session_id, ReconciliationState.PROBABILISTIC_COMPLETE, triggered_by)

    return {
        "layer":          "probabilistic",
        "match_count":    len(result.matches),
        "threshold_used": result.threshold_used,
        "new_state":      rm.get_current_state(session_id).value,
    }
