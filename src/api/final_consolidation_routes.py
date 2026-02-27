"""
Final Consolidation endpoint — Phase 7: ai_review_complete → final_consolidated

Flow:
  1. Guard: session exists
  2. Guard: state is exactly AI_REVIEW_COMPLETE
     - If already FINAL_CONSOLIDATED → specific 409 "already consolidated" message
     - Any other wrong state         → generic 409 "requires ai_review_complete"
  3. Pull matching buckets and residual from runtime (read-only)
  4. Run consolidation (pure function — no side effects on runtime)
  5. Write results BEFORE state advance:
       - rm.write_matching_results("final", ...) — complete consolidated list
       - rm.write_consolidation(...)             — summary metrics
  6. Advance state to FINAL_CONSOLIDATED (snapshot fires automatically)
  7. Return FinalConsolidationResponse

Architecture notes:
- No computation: only assembles already-accepted matches.
- Deterministic layer is authoritative; all included.
- Probabilistic: only user_status == "accepted" included.
- AI: only matches already moved to final bucket by Phase 6A included.
- Residual pool is not modified by this endpoint.
- No recomputation once FINAL_CONSOLIDATED.
"""

from fastapi import APIRouter, HTTPException

import src.core.runtime_manager as rm
from src.core.state_machine import InvalidStateTransition, ReconciliationState
from src.schemas.final_consolidation import ConsolidationSummary, FinalConsolidationResponse
from src.schemas.intake import SnapshotInfo
from src.services.final_consolidation_service import run_final_consolidation

router = APIRouter(prefix="/reconciliation", tags=["consolidation"])


@router.post("/{session_id}/consolidate", response_model=FinalConsolidationResponse)
def run_consolidation(session_id: str):
    """
    Assemble the final reconciliation dataset and advance session from
    'ai_review_complete' to 'final_consolidated'.

    Consolidates:
      - All deterministic matches (authoritative, auto_confirmed)
      - Accepted probabilistic matches (user_status == "accepted")
      - Accepted AI matches (already in final bucket from Phase 6A)

    No recomputation — pure bookkeeping assembly step.

    Returns 409 with an "already consolidated" message if already FINAL_CONSOLIDATED.
    Returns 409 if session is in any other non-ai_review_complete state.
    """
    # --- Guard: session existence ---
    if not rm.session_exists(session_id):
        raise HTTPException(status_code=404, detail=f"Session not found: {session_id}")

    current = rm.get_current_state(session_id)

    # --- Guard: already consolidated ---
    if current == ReconciliationState.FINAL_CONSOLIDATED:
        raise HTTPException(
            status_code=409,
            detail=(
                "Session is already in 'final_consolidated' state. "
                "Final consolidation has already been completed."
            ),
        )

    # --- Guard: correct pre-condition state ---
    if current != ReconciliationState.AI_REVIEW_COMPLETE:
        raise HTTPException(
            status_code=409,
            detail=(
                f"Final consolidation requires state 'ai_review_complete'. "
                f"Current state is '{current.value}'."
            ),
        )

    # --- Pull inputs from runtime (read-only) ---
    runtime      = rm.get_runtime(session_id)
    matching     = runtime["matching"]
    pool         = runtime.get("residual_pool", {})

    det_matches  = matching.get("deterministic", [])
    prob_matches = matching.get("probabilistic", [])
    ai_final     = matching.get("final",         [])
    rejected     = matching.get("rejected",      [])

    residual_gl  = pool.get("gl",        None)
    residual_sub = pool.get("subledger", None)

    # --- Run consolidation (pure, no side effects) ---
    result = run_final_consolidation(
        det_matches=  det_matches,
        prob_matches= prob_matches,
        ai_final=     ai_final,
        rejected=     rejected,
        residual_gl=  residual_gl,
        residual_sub= residual_sub,
    )

    # --- Write results BEFORE state advance so snapshot captures everything ---
    rm.write_matching_results(session_id, "final", result.all_matches)

    rm.write_consolidation(session_id, {
        "deterministic_match_count": result.deterministic_match_count,
        "probabilistic_match_count": result.probabilistic_match_count,
        "ai_match_count":            result.ai_match_count,
        "total_match_count":         result.total_match_count,
        "residual_gl_count":         result.residual_gl_count,
        "residual_sub_count":        result.residual_sub_count,
        "rejected_count":            result.rejected_count,
        "override_count":            result.override_count,
    })

    # --- Advance state (snapshot fires automatically) ---
    try:
        rm.advance_state(
            session_id,
            ReconciliationState.FINAL_CONSOLIDATED,
            triggered_by="consolidation",
        )
    except InvalidStateTransition as exc:
        raise HTTPException(status_code=409, detail=str(exc))

    # --- Build response ---
    snapshots = rm.get_session_snapshots(session_id)
    latest    = snapshots[-1] if snapshots else {}

    return FinalConsolidationResponse(
        session_id= session_id,
        state=      rm.get_current_state(session_id).value,
        summary=ConsolidationSummary(
            deterministic_match_count= result.deterministic_match_count,
            probabilistic_match_count= result.probabilistic_match_count,
            ai_match_count=            result.ai_match_count,
            total_match_count=         result.total_match_count,
            residual_gl_count=         result.residual_gl_count,
            residual_sub_count=        result.residual_sub_count,
            rejected_count=            result.rejected_count,
            override_count=            result.override_count,
        ),
        snapshot=SnapshotInfo(
            key=            latest.get("pre_transition_state", ""),
            integrity_hash= latest.get("integrity_hash", ""),
        ),
    )
