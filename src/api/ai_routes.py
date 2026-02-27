"""
AI endpoints — Phase 6 and Phase 6A.

Phase 6  — POST /{session_id}/ai
  probabilistic_review_complete → ai_suggested
  Generates AI-assisted match suggestions from the residual pool.
  Advisory only — residual pool is never modified.
  No recomputation once AI_SUGGESTED.

Phase 6A — POST /{session_id}/ai/review
  ai_suggested → ai_review_complete
  Applies human accept/reject decisions to AI suggestions.
  Accepted suggestions move to the final bucket.
  Rejected suggestions move to the rejected bucket; records return to residual.
  No re-review once AI_REVIEW_COMPLETE.

Architecture notes:
- Advisory only: residual_pool is NEVER modified by Phase 6.
- Snapshot captures all writes before each state advance.
- No business logic in this file — all mutation inside service layer.
"""

import pandas as pd
from fastapi import APIRouter, HTTPException

import src.core.runtime_manager as rm
from src.core.state_machine import InvalidStateTransition, ReconciliationState
from src.schemas.ai_suggested import (
    AIMatchSchema,
    AIResponse,
    AISummary,
    AIReviewRequest,
    AIReviewResponse,
)
from src.schemas.intake import SnapshotInfo
from src.services.ai_matching_service import (
    DEFAULT_AI_MODEL,
    DEFAULT_PROMPT_VERSION,
    run_ai_matching,
)
from src.services.ai_review_service import process_ai_review

router = APIRouter(prefix="/reconciliation", tags=["ai"])


@router.post("/{session_id}/ai", response_model=AIResponse)
def run_ai_suggested(session_id: str):
    """
    Generate AI-assisted match suggestions and advance session from
    'probabilistic_review_complete' to 'ai_suggested'.

    Advisory only — the residual pool is not modified. All suggestions
    require human review before acceptance.

    Returns 409 with a "no recomputation" message if already AI_SUGGESTED.
    Returns 409 if session is in any other non-probabilistic_review_complete state.
    """
    # --- Guard: session existence ---
    if not rm.session_exists(session_id):
        raise HTTPException(status_code=404, detail=f"Session not found: {session_id}")

    current = rm.get_current_state(session_id)

    # --- Guard: already complete ---
    if current == ReconciliationState.AI_SUGGESTED:
        raise HTTPException(
            status_code=409,
            detail=(
                "Session is already in 'ai_suggested' state. "
                "No recomputation is permitted once AI suggestions are complete."
            ),
        )

    # --- Guard: correct pre-condition state ---
    if current != ReconciliationState.PROBABILISTIC_REVIEW_COMPLETE:
        raise HTTPException(
            status_code=409,
            detail=(
                f"AI suggested matching requires state 'probabilistic_review_complete'. "
                f"Current state is '{current.value}'."
            ),
        )

    # --- Pull inputs from runtime (read-only) ---
    runtime = rm.get_runtime(session_id)
    config  = runtime["config"]
    pool    = runtime.get("residual_pool", {})

    gl_pool  = pool.get("gl")
    sub_pool = pool.get("subledger")

    if gl_pool is None or sub_pool is None:
        raise HTTPException(
            status_code=422,
            detail="residual_pool not available. Ensure prior matching phases are complete.",
        )

    # Resolve model and prompt version from config (fall back to service defaults)
    ai_model       = config.get("ai_model") or DEFAULT_AI_MODEL
    prompt_version = DEFAULT_PROMPT_VERSION

    # --- Run AI matching (pure stub — advisory only, no residual mutation) ---
    try:
        result = run_ai_matching(
            residual_gl=    gl_pool,
            residual_sub=   sub_pool,
            ai_model=       ai_model,
            prompt_version= prompt_version,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    # --- Write results BEFORE state advance so snapshot captures everything ---
    rm.write_matching_results(session_id, "ai_suggested", result.to_suggestion_list())

    rm.write_ai_suggested_meta(session_id, {
        "model_used":       result.model_used,
        "prompt_version":   result.prompt_version,
        "suggestion_count": len(result.suggestions),
    })

    # --- Advance state (snapshot fires automatically) ---
    try:
        rm.advance_state(
            session_id,
            ReconciliationState.AI_SUGGESTED,
            triggered_by="ai",
        )
    except InvalidStateTransition as exc:
        raise HTTPException(status_code=409, detail=str(exc))

    # --- Build response ---
    snapshots = rm.get_session_snapshots(session_id)
    latest    = snapshots[-1] if snapshots else {}

    return AIResponse(
        session_id=  session_id,
        state=       rm.get_current_state(session_id).value,
        summary=AISummary(
            total_residual_gl=  result.total_residual_gl,
            total_residual_sub= result.total_residual_sub,
            suggestion_count=   len(result.suggestions),
            model_used=         result.model_used,
            prompt_version=     result.prompt_version,
        ),
        suggestions=[AIMatchSchema(**s.to_dict()) for s in result.suggestions],
        snapshot=SnapshotInfo(
            key=            latest.get("pre_transition_state", ""),
            integrity_hash= latest.get("integrity_hash", ""),
        ),
    )


@router.post(
    "/{session_id}/ai/review",
    response_model=AIReviewResponse,
)
def confirm_ai_review(session_id: str, body: AIReviewRequest):
    """
    Apply human accept/reject decisions to AI suggestions and advance session
    from 'ai_suggested' to 'ai_review_complete'.

    Accepted suggestions: user_status → "accepted"; moved to final bucket.
    Rejected suggestions: user_status → "rejected"; moved to rejected bucket;
                          GL and Sub records returned to residual pool.
    Undecided suggestions: unchanged (user_status stays "pending").

    Returns 409 with a specific "already confirmed" message if review is already complete.
    Returns 409 if session is in any other non-ai_suggested state.
    """
    # --- Guard: session existence ---
    if not rm.session_exists(session_id):
        raise HTTPException(status_code=404, detail=f"Session not found: {session_id}")

    current = rm.get_current_state(session_id)

    # --- Guard: already reviewed ---
    if current == ReconciliationState.AI_REVIEW_COMPLETE:
        raise HTTPException(
            status_code=409,
            detail=(
                "Session is already in 'ai_review_complete' state. "
                "AI review has already been confirmed."
            ),
        )

    # --- Guard: correct pre-condition state ---
    if current != ReconciliationState.AI_SUGGESTED:
        raise HTTPException(
            status_code=409,
            detail=(
                f"AI review requires state 'ai_suggested'. "
                f"Current state is '{current.value}'."
            ),
        )

    # --- Pull inputs from runtime (read-only) ---
    runtime     = rm.get_runtime(session_id)
    ai_matches  = runtime["matching"].get("ai_suggested", [])
    pool        = runtime.get("residual_pool", {})
    clean       = runtime.get("clean_data", {})

    current_residual_gl  = pool.get("gl",        pd.DataFrame())
    current_residual_sub = pool.get("subledger",  pd.DataFrame())
    clean_gl             = clean.get("gl",        pd.DataFrame())
    clean_sub            = clean.get("subledger", pd.DataFrame())

    existing_final    = runtime["matching"].get("final",    [])
    existing_rejected = runtime["matching"].get("rejected", [])

    # --- Apply decisions (pure, no side effects) ---
    try:
        review = process_ai_review(
            decisions=            [d.model_dump() for d in body.decisions],
            ai_matches=           ai_matches,
            current_residual_gl=  current_residual_gl,
            current_residual_sub= current_residual_sub,
            clean_gl=             clean_gl,
            clean_sub=            clean_sub,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    # --- Write results BEFORE state advance so snapshot captures everything ---
    rm.write_matching_results(
        session_id, "ai_suggested", review.remaining_ai_suggested()
    )
    rm.write_matching_results(
        session_id, "final", existing_final + review.accepted_matches
    )
    rm.write_matching_results(
        session_id, "rejected", existing_rejected + review.rejected_matches
    )
    rm.write_residual_pool(session_id, {
        "gl":        review.updated_residual_gl,
        "subledger": review.updated_residual_sub,
    })

    # --- Advance state (snapshot fires automatically) ---
    try:
        rm.advance_state(
            session_id,
            ReconciliationState.AI_REVIEW_COMPLETE,
            triggered_by="ai_review",
        )
    except InvalidStateTransition as exc:
        raise HTTPException(status_code=409, detail=str(exc))

    # --- Build response ---
    snapshots = rm.get_session_snapshots(session_id)
    latest    = snapshots[-1] if snapshots else {}

    return AIReviewResponse(
        session_id=     session_id,
        state=          rm.get_current_state(session_id).value,
        accepted_count= review.accepted_count,
        rejected_count= review.rejected_count,
        snapshot=SnapshotInfo(
            key=            latest.get("pre_transition_state", ""),
            integrity_hash= latest.get("integrity_hash", ""),
        ),
    )
