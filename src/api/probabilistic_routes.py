"""
Probabilistic endpoints — Phase 5 and Phase 5A.

Phase 5  — POST /{session_id}/probabilistic
  deterministic_review_complete → probabilistic_complete
  Runs the 3-step probabilistic matching pipeline on the residual pool.

Phase 5A — POST /{session_id}/probabilistic/review
  probabilistic_complete → probabilistic_review_complete
  Applies human accept/reject decisions to probabilistic matches.
  Rejected matches move to the rejected bucket; their records return to the residual pool.

Architecture notes:
- Phase 5  operates exclusively on residual_pool; never touches matching["deterministic"].
- Phase 5A is the ONLY place user_status transitions from "pending" to "accepted"/"rejected".
- All writes happen BEFORE advance_state() so the snapshot captures the full dataset.
- No recomputation once PROBABILISTIC_COMPLETE (Phase 5 guard).
- No re-review once PROBABILISTIC_REVIEW_COMPLETE (Phase 5A guard).
"""

from typing import Any, Dict, List

import numpy as np
import pandas as pd
from fastapi import APIRouter, HTTPException

import src.core.runtime_manager as rm
from src.core.state_machine import InvalidStateTransition, ReconciliationState
from src.schemas.probabilistic import (
    ProbabilisticMatchSchema,
    ProbabilisticResponse,
    ProbabilisticReviewRequest,
    ProbabilisticReviewResponse,
    ProbabilisticSummary,
)
from src.schemas.intake import SnapshotInfo
from src.services.probabilistic_matching import (
    DEFAULT_THRESHOLD,
    DEFAULT_WEIGHTS,
    run_probabilistic_matching,
)
from src.services.probabilistic_review_service import process_probabilistic_review

router = APIRouter(prefix="/reconciliation", tags=["probabilistic"])


# ── Serialisation helpers (mirrors deterministic_routes) ──────────────────────

def _coerce(v: Any) -> Any:
    if isinstance(v, np.integer):
        return int(v)
    if isinstance(v, np.floating):
        return None if np.isnan(v) else float(v)
    if isinstance(v, np.bool_):
        return bool(v)
    if isinstance(v, float) and np.isnan(v):
        return None
    return v


def _serialize_df(df: pd.DataFrame) -> List[Dict[str, Any]]:
    if df is None or df.empty:
        return []
    df_copy = df.copy()
    for col in df_copy.select_dtypes(include=["datetime64[ns]", "datetimetz"]).columns:
        df_copy[col] = df_copy[col].dt.strftime("%Y-%m-%d")
    df_copy = df_copy.where(df_copy.notna(), other=None)
    records = df_copy.to_dict(orient="records")
    return [{k: _coerce(v) for k, v in row.items()} for row in records]


@router.post("/{session_id}/probabilistic", response_model=ProbabilisticResponse)
def run_probabilistic(session_id: str):
    """
    Run probabilistic matching and advance session from
    'deterministic_review_complete' to 'probabilistic_complete'.

    Returns 409 with a "no recomputation" message if already complete.
    Returns 409 if session is in any other non-deterministic_review_complete state.
    """
    # --- Guard: session existence ---
    if not rm.session_exists(session_id):
        raise HTTPException(status_code=404, detail=f"Session not found: {session_id}")

    current = rm.get_current_state(session_id)

    # --- Guard: already complete ---
    if current == ReconciliationState.PROBABILISTIC_COMPLETE:
        raise HTTPException(
            status_code=409,
            detail=(
                "Session is already in 'probabilistic_complete' state. "
                "No recomputation is permitted once probabilistic matching is complete."
            ),
        )

    # --- Guard: correct pre-condition state ---
    if current != ReconciliationState.DETERMINISTIC_REVIEW_COMPLETE:
        raise HTTPException(
            status_code=409,
            detail=(
                f"Probabilistic matching requires state 'deterministic_review_complete'. "
                f"Current state is '{current.value}'."
            ),
        )

    # --- Pull inputs from runtime ---
    runtime  = rm.get_runtime(session_id)
    config   = runtime["config"]
    pool     = runtime.get("residual_pool", {})

    gl_pool  = pool.get("gl")
    sub_pool = pool.get("subledger")

    if gl_pool is None or sub_pool is None:
        raise HTTPException(
            status_code=422,
            detail="residual_pool not available. Ensure deterministic matching is complete.",
        )

    # Resolve threshold and weights — matching_config.probabilistic takes priority,
    # then legacy runtime config keys, then service defaults.
    matching_prob_config = config.get("matching_config", {}).get("probabilistic") or {}
    column_map  = config.get("column_map")
    if matching_prob_config:
        # Use AI-confirmed matching config
        threshold = matching_prob_config.get("threshold", DEFAULT_THRESHOLD)
        weights   = matching_prob_config.get("weights", DEFAULT_WEIGHTS)
    else:
        # Legacy fallback: runtime config keys
        threshold   = config.get("threshold") or DEFAULT_THRESHOLD
        raw_weights = config.get("weights") or {}
        weights     = {**DEFAULT_WEIGHTS, **raw_weights}

    # --- Run matching pipeline (pure, no side effects) ---
    try:
        result = run_probabilistic_matching(
            gl_pool=     gl_pool,
            sub_pool=    sub_pool,
            threshold=   threshold,
            weights=     weights,
            column_map=  column_map,
            prob_config= matching_prob_config if matching_prob_config else None,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    # --- Write results BEFORE state advance so snapshot captures everything ---
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

    # --- Advance state (snapshot fires automatically) ---
    try:
        rm.advance_state(
            session_id,
            ReconciliationState.PROBABILISTIC_COMPLETE,
            triggered_by="probabilistic",
        )
    except InvalidStateTransition as exc:
        raise HTTPException(status_code=409, detail=str(exc))

    # --- Collect record IDs referenced by matches (to slim the payload) ---
    gl_ids_matched: set = set()
    sub_ids_matched: set = set()
    for m in result.matches:
        for rid in m.record_ids_A:
            gl_ids_matched.add(str(rid))
        for rid in m.record_ids_B:
            sub_ids_matched.add(str(rid))

    matched_gl_df = (
        gl_pool[gl_pool["gl_id"].astype(str).isin(gl_ids_matched)]
        if not gl_pool.empty and "gl_id" in gl_pool.columns
        else pd.DataFrame()
    )
    matched_sub_df = (
        sub_pool[sub_pool["subledger_id"].astype(str).isin(sub_ids_matched)]
        if not sub_pool.empty and "subledger_id" in sub_pool.columns
        else pd.DataFrame()
    )

    # --- Build response ---
    snapshots = rm.get_session_snapshots(session_id)
    latest    = snapshots[-1] if snapshots else {}

    return ProbabilisticResponse(
        session_id=session_id,
        state=rm.get_current_state(session_id).value,
        summary=ProbabilisticSummary(
            total_gl_records=     result.total_gl,
            total_sub_records=    result.total_sub,
            matched_gl_records=   result.matched_gl,
            matched_sub_records=  result.matched_sub,
            unmatched_gl_records= len(result.residual_gl),
            unmatched_sub_records=len(result.residual_sub),
            match_count=          len(result.matches),
            threshold_used=       result.threshold_used,
            weights_used=         result.weights_used,
        ),
        matches=[ProbabilisticMatchSchema(**m.to_dict()) for m in result.matches],
        gl_pool_records= _serialize_df(matched_gl_df),
        sub_pool_records=_serialize_df(matched_sub_df),
        snapshot=SnapshotInfo(
            key=            latest.get("pre_transition_state", ""),
            integrity_hash= latest.get("integrity_hash", ""),
        ),
    )


@router.post(
    "/{session_id}/probabilistic/review",
    response_model=ProbabilisticReviewResponse,
)
def confirm_probabilistic_review(session_id: str, body: ProbabilisticReviewRequest):
    """
    Apply human accept/reject decisions to probabilistic matches and advance session
    from 'probabilistic_complete' to 'probabilistic_review_complete'.

    Accepted matches:  user_status → "accepted"; remain in probabilistic bucket.
    Rejected matches:  user_status → "rejected"; moved to rejected bucket;
                       GL and Sub records returned to residual pool.
    Undecided matches: unchanged (user_status stays "pending").

    Returns 409 with a specific "already reviewed" message if review is already complete.
    Returns 409 if session is in any other non-probabilistic_complete state.
    """
    # --- Guard: session existence ---
    if not rm.session_exists(session_id):
        raise HTTPException(status_code=404, detail=f"Session not found: {session_id}")

    current = rm.get_current_state(session_id)

    # --- Guard: already reviewed ---
    if current == ReconciliationState.PROBABILISTIC_REVIEW_COMPLETE:
        raise HTTPException(
            status_code=409,
            detail=(
                "Session is already in 'probabilistic_review_complete' state. "
                "Probabilistic review has already been confirmed."
            ),
        )

    # --- Guard: correct pre-condition state ---
    if current != ReconciliationState.PROBABILISTIC_COMPLETE:
        raise HTTPException(
            status_code=409,
            detail=(
                f"Probabilistic review requires state 'probabilistic_complete'. "
                f"Current state is '{current.value}'."
            ),
        )

    # --- Pull inputs from runtime (read-only) ---
    runtime      = rm.get_runtime(session_id)
    prob_matches = runtime["matching"].get("probabilistic", [])
    pool         = runtime.get("residual_pool", {})
    clean        = runtime.get("clean_data", {})

    current_residual_gl  = pool.get("gl",        pd.DataFrame())
    current_residual_sub = pool.get("subledger",  pd.DataFrame())
    clean_gl             = clean.get("gl",         pd.DataFrame())
    clean_sub            = clean.get("subledger",  pd.DataFrame())

    existing_rejected = runtime["matching"].get("rejected", [])

    # --- Apply decisions (pure, no side effects) ---
    try:
        review = process_probabilistic_review(
            decisions=           [d.model_dump() for d in body.decisions],
            prob_matches=        prob_matches,
            current_residual_gl=  current_residual_gl,
            current_residual_sub= current_residual_sub,
            clean_gl=            clean_gl,
            clean_sub=           clean_sub,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    # --- Write results BEFORE state advance so snapshot captures everything ---
    rm.write_matching_results(
        session_id, "probabilistic", review.remaining_probabilistic()
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
            ReconciliationState.PROBABILISTIC_REVIEW_COMPLETE,
            triggered_by="probabilistic_review",
        )
    except InvalidStateTransition as exc:
        raise HTTPException(status_code=409, detail=str(exc))

    # --- Build response ---
    snapshots = rm.get_session_snapshots(session_id)
    latest    = snapshots[-1] if snapshots else {}

    return ProbabilisticReviewResponse(
        session_id=     session_id,
        state=          rm.get_current_state(session_id).value,
        accepted_count= review.accepted_count,
        rejected_count= review.rejected_count,
        snapshot=SnapshotInfo(
            key=            latest.get("pre_transition_state", ""),
            integrity_hash= latest.get("integrity_hash", ""),
        ),
    )
