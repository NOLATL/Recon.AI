"""
Deterministic matching layer.

Authority: AUTHORITATIVE — results from this layer are treated as ground truth.
Activation: PREPROCESSED → DETERMINISTIC_COMPLETE

Architecture contracts:
- Must call runtime_manager.assert_not_in_review() before any computation
- Must write results via runtime_manager.write_matching_results("deterministic", ...)
- Must NOT read from or write to any other session's runtime
- Business logic lives in src.services.deterministic_matching; this module delegates to it
"""

import src.core.runtime_manager as rm
from src.core.state_machine import ReconciliationState
from src.services.deterministic_matching import run_deterministic_matching


def run(session_id: str, triggered_by: str = "system") -> dict:
    """
    Execute deterministic matching for the session.

    Expected pre-condition:  current_state == PREPROCESSED
    Post-condition:          current_state == DETERMINISTIC_COMPLETE
                             runtime["matching"]["deterministic"] populated
                             runtime["residual_pool"] populated

    Returns a summary dict with match counts (not the raw records).
    """
    rm.assert_not_in_review(session_id)

    runtime    = rm.get_runtime(session_id)
    clean_data = runtime.get("clean_data", {})
    gl_df      = clean_data.get("gl")
    sub_df     = clean_data.get("subledger")

    if gl_df is None or sub_df is None:
        raise ValueError(
            "clean_data not available. Ensure preprocessing is complete before "
            "running the deterministic layer."
        )

    result = run_deterministic_matching(gl_df=gl_df, sub_df=sub_df)

    rm.write_matching_results(session_id, "deterministic", result.to_match_list())
    rm.write_residual_pool(session_id, {
        "gl":        result.residual_gl,
        "subledger": result.residual_sub,
    })

    rm.advance_state(session_id, ReconciliationState.DETERMINISTIC_COMPLETE, triggered_by)

    return {
        "layer":         "deterministic",
        "matched_count": len(result.matches),
        "new_state":     rm.get_current_state(session_id).value,
    }
