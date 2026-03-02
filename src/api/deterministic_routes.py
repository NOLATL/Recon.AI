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

from collections import defaultdict
from typing import Any, Dict, List, Set

import numpy as np
import pandas as pd
from fastapi import APIRouter, HTTPException

import src.core.runtime_manager as rm
from src.core.state_machine import InvalidStateTransition, ReconciliationState
from src.schemas.deterministic import (
    DeterministicResponse,
    DeterministicReviewResponse,
    DeterministicSummary,
    MatchRecordSchema,
    ScenarioAmountSummary,
)
from src.schemas.intake import SnapshotInfo
from src.services.deterministic_matching import DeterministicResult, run_deterministic_matching

router = APIRouter(prefix="/reconciliation", tags=["deterministic"])


# ---------------------------------------------------------------------------
# Serialisation helpers
# ---------------------------------------------------------------------------

def _coerce(v: Any) -> Any:
    """Convert numpy scalar types to plain Python primitives for JSON safety."""
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
    """Serialise a DataFrame to a JSON-safe list of dicts.

    Steps:
      1. Stringify all datetime columns (→ YYYY-MM-DD).
      2. Replace NaN / NaT with None.
      3. Coerce numpy scalar types to Python primitives.
    """
    if df is None or df.empty:
        return []

    df_copy = df.copy()

    # Stringify datetime columns
    for col in df_copy.select_dtypes(include=["datetime64[ns]", "datetimetz"]).columns:
        df_copy[col] = df_copy[col].dt.strftime("%Y-%m-%d")

    # Replace NaN with None
    df_copy = df_copy.where(df_copy.notna(), other=None)

    records = df_copy.to_dict(orient="records")
    return [{k: _coerce(v) for k, v in row.items()} for row in records]


def _compute_dollar_totals(
    result: DeterministicResult,
    gl_df: pd.DataFrame,
    sub_df: pd.DataFrame,
) -> tuple[float, float, List[ScenarioAmountSummary]]:
    """Compute matched dollar amounts globally and per scenario.

    Returns:
        (total_matched_gl_amount, total_matched_sub_amount, scenario_amount_summaries)
    """
    # Build id → amount lookup (str keys for reliable set intersection)
    gl_amount_map: Dict[str, float] = dict(
        zip(
            gl_df["gl_id"].astype(str),
            pd.to_numeric(gl_df["amount"], errors="coerce").fillna(0.0),
        )
    )
    sub_amount_map: Dict[str, float] = dict(
        zip(
            sub_df["subledger_id"].astype(str),
            pd.to_numeric(sub_df["amount"], errors="coerce").fillna(0.0),
        )
    )

    all_gl_ids: Set[str] = set()
    all_sub_ids: Set[str] = set()
    scenario_gl: Dict[int, Set[str]] = defaultdict(set)
    scenario_sub: Dict[int, Set[str]] = defaultdict(set)

    for m in result.matches:
        all_gl_ids.update(m.record_ids_A)
        all_sub_ids.update(m.record_ids_B)
        scenario_gl[m.scenario_id].update(m.record_ids_A)
        scenario_sub[m.scenario_id].update(m.record_ids_B)

    total_gl  = round(sum(gl_amount_map.get(i, 0.0)  for i in all_gl_ids),  2)
    total_sub = round(sum(sub_amount_map.get(i, 0.0) for i in all_sub_ids), 2)

    summaries: List[ScenarioAmountSummary] = []
    for sc_id in sorted(scenario_gl.keys()):
        sc_gl  = round(sum(gl_amount_map.get(i, 0.0)  for i in scenario_gl[sc_id]),  2)
        sc_sub = round(sum(sub_amount_map.get(i, 0.0) for i in scenario_sub[sc_id]), 2)
        summaries.append(
            ScenarioAmountSummary(
                scenario_id=sc_id,
                match_count=result.scenario_counts.get(sc_id, 0),
                total_gl_amount=sc_gl,
                total_sub_amount=sc_sub,
            )
        )

    return total_gl, total_sub, summaries


# ---------------------------------------------------------------------------
# Phase 4 — Run deterministic matching
# ---------------------------------------------------------------------------

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
    runtime = rm.get_runtime(session_id)
    clean   = runtime.get("clean_data", {})
    gl_df   = clean.get("gl")
    sub_df  = clean.get("subledger")

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

    # --- Compute dollar totals ---
    total_gl_amount, total_sub_amount, scenario_summaries = _compute_dollar_totals(
        result, gl_df, sub_df
    )

    # --- Build response ---
    snapshots = rm.get_session_snapshots(session_id)
    latest    = snapshots[-1] if snapshots else {}

    return DeterministicResponse(
        session_id=session_id,
        state=rm.get_current_state(session_id).value,
        summary=DeterministicSummary(
            total_gl_records=          result.total_gl,
            total_sub_records=         result.total_sub,
            matched_gl_records=        result.matched_gl,
            matched_sub_records=       result.matched_sub,
            unmatched_gl_records=      len(result.residual_gl),
            unmatched_sub_records=     len(result.residual_sub),
            match_count=               len(result.matches),
            scenario_counts=           result.scenario_counts,
            total_matched_gl_amount=   total_gl_amount,
            total_matched_sub_amount=  total_sub_amount,
            scenario_amount_summaries= scenario_summaries,
        ),
        matches=[MatchRecordSchema(**m.to_dict()) for m in result.matches],
        gl_records=           _serialize_df(gl_df),
        sub_records=          _serialize_df(sub_df),
        residual_gl_records=  _serialize_df(result.residual_gl),
        residual_sub_records= _serialize_df(result.residual_sub),
        snapshot=SnapshotInfo(
            key=            latest.get("pre_transition_state", ""),
            integrity_hash= latest.get("integrity_hash", ""),
        ),
    )


# ---------------------------------------------------------------------------
# Phase 4A — Confirm deterministic review
# ---------------------------------------------------------------------------

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
