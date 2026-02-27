"""
Deterministic endpoints — Phase 4 and Phase 4A.

Phase 4  — POST /{session_id}/deterministic
  preprocessed → deterministic_complete
  Runs the 4-scenario deterministic matching pipeline.

Phase 4A — POST /{session_id}/deterministic/review
  deterministic_complete → deterministic_review_complete
  Confirm-only: no computation, no dataset mutation.
  Advances state to unlock the probabilistic layer.
  Snapshot fires automatically inside advance_state().

Architecture notes:
- All dataset writes happen BEFORE advance_state() (Phase 4 only).
- Review endpoint never mutates any dataset.
- Both endpoints reject recomputation once their target state is reached.
"""

from fastapi import APIRouter, HTTPException

import src.core.runtime_manager as rm
from src.core.state_machine import InvalidStateTransition, ReconciliationState
from src.schemas.deterministic import (
    DeterministicResponse,
    DeterministicReviewResponse,
    DeterministicSummary,
    MatchRecordSchema,
)
from src.schemas.intake import SnapshotInfo
from src.services.deterministic_matching import run_deterministic_matching

router = APIRouter(prefix="/reconciliation", tags=["deterministic"])


@router.post("/{session_id}/deterministic", response_model=DeterministicResponse)
def run_deterministic(session_id: str):
    """
    Run deterministic matching and advance session from 'preprocessed' to
    'deterministic_complete'.

    Returns 409 with a specific "no recomputation" message if already complete.
    Returns 409 if session is in any other non-preprocessed state.
    """
    # --- Guard: session existence ---
    if not rm.session_exists(session_id):
        raise HTTPException(status_code=404, detail=f"Session not found: {session_id}")

    current = rm.get_current_state(session_id)

    # --- Guard: already complete (explicit, distinct from generic wrong-state) ---
    if current == ReconciliationState.DETERMINISTIC_COMPLETE:
        raise HTTPException(
            status_code=409,
            detail=(
                "Session is already in 'deterministic_complete' state. "
                "No recomputation is permitted once deterministic matching is complete."
            ),
        )

    # --- Guard: correct pre-condition state ---
    if current != ReconciliationState.PREPROCESSED:
        raise HTTPException(
            status_code=409,
            detail=(
                f"Deterministic matching requires state 'preprocessed'. "
                f"Current state is '{current.value}'."
            ),
        )

    # --- Pull inputs from runtime ---
    runtime   = rm.get_runtime(session_id)
    clean     = runtime.get("clean_data", {})
    gl_df     = clean.get("gl")
    sub_df    = clean.get("subledger")

    if gl_df is None or sub_df is None:
        raise HTTPException(
            status_code=422,
            detail="clean_data not available. Ensure preprocessing is complete.",
        )

    # --- Run matching pipeline (pure, no side effects) ---
    try:
        result = run_deterministic_matching(gl_df=gl_df, sub_df=sub_df)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    # --- Write results BEFORE state advance so snapshot captures everything ---
    rm.write_matching_results(session_id, "deterministic", result.to_match_list())

    rm.write_residual_pool(session_id, {
        "gl":        result.residual_gl,
        "subledger": result.residual_sub,
    })

    # --- Advance state (snapshot fires automatically) ---
    try:
        rm.advance_state(
            session_id,
            ReconciliationState.DETERMINISTIC_COMPLETE,
            triggered_by="deterministic",
        )
    except InvalidStateTransition as exc:
        raise HTTPException(status_code=409, detail=str(exc))

    # --- Build response ---
    snapshots = rm.get_session_snapshots(session_id)
    latest    = snapshots[-1] if snapshots else {}

    return DeterministicResponse(
        session_id=session_id,
        state=rm.get_current_state(session_id).value,
        summary=DeterministicSummary(
            total_gl_records=     result.total_gl,
            total_sub_records=    result.total_sub,
            matched_gl_records=   result.matched_gl,
            matched_sub_records=  result.matched_sub,
            unmatched_gl_records= len(result.residual_gl),
            unmatched_sub_records=len(result.residual_sub),
            match_count=          len(result.matches),
            scenario_counts=      result.scenario_counts,
        ),
        matches=[MatchRecordSchema(**m.to_dict()) for m in result.matches],
        snapshot=SnapshotInfo(
            key=            latest.get("pre_transition_state", ""),
            integrity_hash= latest.get("integrity_hash", ""),
        ),
    )


@router.post(
    "/{session_id}/deterministic/review",
    response_model=DeterministicReviewResponse,
)
def confirm_deterministic_review(session_id: str):
    """
    Confirm deterministic review and advance session from 'deterministic_complete'
    to 'deterministic_review_complete'.

    Confirm-only — no computation, no dataset mutation.
    Snapshot is written automatically before the state advance.

    Returns 409 with a specific "already confirmed" message if review is already complete.
    Returns 409 if the session is in any other non-deterministic_complete state.
    """
    # --- Guard: session existence ---
    if not rm.session_exists(session_id):
        raise HTTPException(status_code=404, detail=f"Session not found: {session_id}")

    current = rm.get_current_state(session_id)

    # --- Guard: already confirmed (explicit, distinct from generic wrong-state) ---
    if current == ReconciliationState.DETERMINISTIC_REVIEW_COMPLETE:
        raise HTTPException(
            status_code=409,
            detail=(
                "Session is already in 'deterministic_review_complete' state. "
                "Deterministic review has already been confirmed."
            ),
        )

    # --- Guard: correct pre-condition state ---
    if current != ReconciliationState.DETERMINISTIC_COMPLETE:
        raise HTTPException(
            status_code=409,
            detail=(
                f"Deterministic review requires state 'deterministic_complete'. "
                f"Current state is '{current.value}'."
            ),
        )

    # --- Read counts (read-only — no mutation) ---
    runtime  = rm.get_runtime(session_id)
    det_list = runtime["matching"].get("deterministic", [])
    pool     = runtime.get("residual_pool", {})
    gl_pool  = pool.get("gl")
    sub_pool = pool.get("subledger")

    residual_gl_count  = len(gl_pool)  if gl_pool  is not None else 0
    residual_sub_count = len(sub_pool) if sub_pool is not None else 0

    # --- Advance state (snapshot fires automatically before mutation) ---
    try:
        rm.advance_state(
            session_id,
            ReconciliationState.DETERMINISTIC_REVIEW_COMPLETE,
            triggered_by="deterministic_review",
        )
    except InvalidStateTransition as exc:
        raise HTTPException(status_code=409, detail=str(exc))

    # --- Build response ---
    snapshots = rm.get_session_snapshots(session_id)
    latest    = snapshots[-1] if snapshots else {}

    return DeterministicReviewResponse(
        session_id=                session_id,
        state=                     rm.get_current_state(session_id).value,
        deterministic_match_count= len(det_list),
        residual_gl_count=         residual_gl_count,
        residual_sub_count=        residual_sub_count,
        snapshot=SnapshotInfo(
            key=            latest.get("pre_transition_state", ""),
            integrity_hash= latest.get("integrity_hash", ""),
        ),
    )
