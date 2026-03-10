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

from typing import Any, Dict, List, Tuple

import numpy as np
import pandas as pd
from fastapi import APIRouter, HTTPException

import src.core.runtime_manager as rm
from src.core.state_machine import InvalidStateTransition, ReconciliationState
from src.schemas.final_consolidation import ConsolidationSummary, FinalConsolidationResponse
from src.schemas.intake import SnapshotInfo
from src.services.final_consolidation_service import run_final_consolidation
from src.services.summary_narrative_service import generate_summary_narrative


# ── Serialisation helpers ────────────────────────────────────────────────────

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


def _serialize_matches(matches: list, layer: str) -> List[Dict[str, Any]]:
    """Coerce match dicts and tag each with its source layer."""
    result = []
    for m in matches:
        coerced = {k: _coerce(v) if not isinstance(v, (list, dict)) else v
                   for k, v in m.items()}
        coerced["layer"] = layer
        result.append(coerced)
    return result

router = APIRouter(prefix="/reconciliation", tags=["consolidation"])


# ── Shared response builder ───────────────────────────────────────────────────

def _build_response(session_id: str) -> FinalConsolidationResponse:
    """Assemble FinalConsolidationResponse from current runtime state (read-only, pure)."""
    runtime      = rm.get_runtime(session_id)
    matching     = runtime["matching"]
    pool         = runtime.get("residual_pool", {})
    clean        = runtime.get("clean_data", {})

    det_matches  = matching.get("deterministic", [])
    prob_matches = matching.get("probabilistic", [])
    # Filter matching["final"] to ONLY real AI matches (have "ai_confidence_score").
    # Deterministic/probabilistic matches written there by a previous bug will not
    # have this field and are silently excluded, making _build_response idempotent.
    ai_final     = [m for m in matching.get("final", []) if "ai_confidence_score" in m]
    rejected     = matching.get("rejected",      [])

    residual_gl  = pool.get("gl",        None)
    residual_sub = pool.get("subledger", None)

    clean_gl  = clean.get("gl",        pd.DataFrame())
    clean_sub = clean.get("subledger", pd.DataFrame())

    result = run_final_consolidation(
        det_matches=  det_matches,
        prob_matches= prob_matches,
        ai_final=     ai_final,
        rejected=     rejected,
        residual_gl=  residual_gl,
        residual_sub= residual_sub,
    )

    dc = result.deterministic_match_count
    pc = result.probabilistic_match_count
    tagged_final = (
        _serialize_matches(result.all_matches[:dc],         "deterministic") +
        _serialize_matches(result.all_matches[dc:dc + pc],  "probabilistic") +
        _serialize_matches(result.all_matches[dc + pc:],    "ai")
    )
    tagged_rejected = _serialize_matches(rejected, "rejected")

    gl_ids_used:  set = set()
    sub_ids_used: set = set()
    for m in result.all_matches:
        for rid in m.get("record_ids_A", []):
            gl_ids_used.add(str(rid))
        for rid in m.get("record_ids_B", []):
            sub_ids_used.add(str(rid))

    matched_gl_df = (
        clean_gl[clean_gl["gl_id"].astype(str).isin(gl_ids_used)]
        if not clean_gl.empty and "gl_id" in clean_gl.columns
        else pd.DataFrame()
    )
    matched_sub_df = (
        clean_sub[clean_sub["subledger_id"].astype(str).isin(sub_ids_used)]
        if not clean_sub.empty and "subledger_id" in clean_sub.columns
        else pd.DataFrame()
    )

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
        final_matches=        tagged_final,
        gl_records=           _serialize_df(matched_gl_df),
        sub_records=          _serialize_df(matched_sub_df),
        residual_gl_records=  _serialize_df(residual_gl  if residual_gl  is not None else pd.DataFrame()),
        residual_sub_records= _serialize_df(residual_sub if residual_sub is not None else pd.DataFrame()),
        rejected_matches=     tagged_rejected,
        snapshot=SnapshotInfo(
            key=            latest.get("pre_transition_state", ""),
            integrity_hash= latest.get("integrity_hash", ""),
        ),
    )


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

    # --- Run consolidation (pure, no side effects) and write results ---
    runtime      = rm.get_runtime(session_id)
    matching     = runtime["matching"]
    pool         = runtime.get("residual_pool", {})
    clean        = runtime.get("clean_data", {})

    det_matches  = matching.get("deterministic", [])
    prob_matches = matching.get("probabilistic", [])
    ai_final     = matching.get("final",         [])
    rejected     = matching.get("rejected",      [])
    residual_gl  = pool.get("gl",        None)
    residual_sub = pool.get("subledger", None)
    clean_gl     = clean.get("gl",        pd.DataFrame())
    clean_sub    = clean.get("subledger", pd.DataFrame())

    result = run_final_consolidation(
        det_matches=  det_matches,
        prob_matches= prob_matches,
        ai_final=     ai_final,
        rejected=     rejected,
        residual_gl=  residual_gl,
        residual_sub= residual_sub,
    )

    # --- Build response from result BEFORE writing to runtime.
    #     Writing all_matches to runtime["matching"]["final"] would cause
    #     _build_response to re-read an inflated "final" bucket and double-count
    #     ai_match_count. We build the response inline here instead. ---
    dc = result.deterministic_match_count
    pc = result.probabilistic_match_count
    tagged_final = (
        _serialize_matches(result.all_matches[:dc],         "deterministic") +
        _serialize_matches(result.all_matches[dc:dc + pc],  "probabilistic") +
        _serialize_matches(result.all_matches[dc + pc:],    "ai")
    )
    tagged_rejected = _serialize_matches(rejected, "rejected")

    gl_ids_used:  set = set()
    sub_ids_used: set = set()
    for m in result.all_matches:
        for rid in m.get("record_ids_A", []):
            gl_ids_used.add(str(rid))
        for rid in m.get("record_ids_B", []):
            sub_ids_used.add(str(rid))

    matched_gl_df = (
        clean_gl[clean_gl["gl_id"].astype(str).isin(gl_ids_used)]
        if not clean_gl.empty and "gl_id" in clean_gl.columns
        else pd.DataFrame()
    )
    matched_sub_df = (
        clean_sub[clean_sub["subledger_id"].astype(str).isin(sub_ids_used)]
        if not clean_sub.empty and "subledger_id" in clean_sub.columns
        else pd.DataFrame()
    )

    # --- Write results BEFORE state advance so snapshot captures everything ---
    # NOTE: do NOT write result.all_matches to matching["final"] — that key holds
    # only Phase 6A AI-accepted matches and must remain unchanged so that
    # _build_response (GET) can correctly separate AI from deterministic/probabilistic.
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
        final_matches=        tagged_final,
        gl_records=           _serialize_df(matched_gl_df),
        sub_records=          _serialize_df(matched_sub_df),
        residual_gl_records=  _serialize_df(residual_gl  if residual_gl  is not None else pd.DataFrame()),
        residual_sub_records= _serialize_df(residual_sub if residual_sub is not None else pd.DataFrame()),
        rejected_matches=     tagged_rejected,
        snapshot=SnapshotInfo(
            key=            latest.get("pre_transition_state", ""),
            integrity_hash= latest.get("integrity_hash", ""),
        ),
    )


@router.get("/{session_id}/narrative")
def get_summary_narrative(session_id: str):
    """
    Generate and return an AI-powered post-reconciliation narrative.

    Covers:
      1. Processing overview (phases, volumes, methods).
      2. Results summary (match counts/rates by layer, residual exposure).
      3. Patterns, takeaways, and suggestions to improve future match rates.

    Available once the session is in ``final_consolidated`` or ``finalized`` state.
    Falls back to a deterministic template when OPENAI_API_KEY is absent.
    """
    if not rm.session_exists(session_id):
        raise HTTPException(status_code=404, detail=f"Session not found: {session_id}")

    current = rm.get_current_state(session_id)
    if current not in (ReconciliationState.FINAL_CONSOLIDATED, ReconciliationState.FINALIZED):
        raise HTTPException(
            status_code=409,
            detail=(
                f"Narrative is only available in 'final_consolidated' or 'finalized' state. "
                f"Current state is '{current.value}'."
            ),
        )

    consolidation = rm.get_runtime(session_id).get("consolidation", {})
    total_match = consolidation.get("total_match_count", 0)
    residual_gl = consolidation.get("residual_gl_count", 0)
    summary_data = {
        "perspective": "GL",
        "note": "All counts and amounts are from the General Ledger perspective only.",
        "summary": {
            "gl_total_count":            total_match + residual_gl,
            "gl_matched_count":          total_match,
            "gl_unmatched_count":        residual_gl,
            "match_rate_pct":            round(total_match / (total_match + residual_gl) * 100, 1) if (total_match + residual_gl) > 0 else 0,
            "deterministic_match_count": consolidation.get("deterministic_match_count", 0),
            "probabilistic_match_count": consolidation.get("probabilistic_match_count", 0),
            "ai_match_count":            consolidation.get("ai_match_count",            0),
            "rejected_count":            consolidation.get("rejected_count",            0),
            "override_count":            consolidation.get("override_count",            0),
        }
    }

    narrative = generate_summary_narrative(summary_data)
    return {"narrative": narrative}


@router.get("/{session_id}/consolidate", response_model=FinalConsolidationResponse)
def get_consolidation_result(session_id: str):
    """
    Retrieve the full consolidation result for a session that is already in
    'final_consolidated' or 'finalized' state.

    Allows the frontend to reload analytics (BANS, match table, residuals) after
    navigation or page refresh without re-running consolidation.

    Uses the same pure assembly logic as the POST endpoint — no side effects.
    Returns 409 if the session has not yet been consolidated.
    """
    if not rm.session_exists(session_id):
        raise HTTPException(status_code=404, detail=f"Session not found: {session_id}")

    current = rm.get_current_state(session_id)
    if current not in (ReconciliationState.FINAL_CONSOLIDATED, ReconciliationState.FINALIZED):
        raise HTTPException(
            status_code=409,
            detail=(
                f"Consolidation results are only available in 'final_consolidated' or "
                f"'finalized' state.  Current state is '{current.value}'."
            ),
        )

    return _build_response(session_id)
