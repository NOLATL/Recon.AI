"""
Preprocessing endpoint — Phase 3: profiled → preprocessed

Flow:
  1. Guard: session exists
  2. Guard: state is exactly PROFILED
     - If already PREPROCESSED → specific 409 "no recomputation" message
     - Any other wrong state → generic 409
  3. Pull raw GL + Subledger DataFrames and config from runtime
  4. Run 3-tier vendor normalization (pure, no side effects on runtime)
  5. Write results to runtime BEFORE state advance:
       - rm.write_vendor_normalization_map()  — authoritative mapping list
       - rm.write_clean_data()                — GL + Subledger with Vendor_Normalized
       - rm.write_preprocessing()             — threshold used, alias version, tier counts
  6. Advance state to PREPROCESSED (snapshot fires automatically inside transition)
  7. Return PreprocessingResponse

Architecture notes:
- All three write calls happen BEFORE advance_state() so the snapshot that fires
  inside StateManager.transition() captures clean datasets + mapping + metadata.
- No direct dict mutation — all writes through controlled rm.write_*() functions.
- No recomputation: once PREPROCESSED, endpoint rejects further calls with a
  distinct error message.
"""

from fastapi import APIRouter, HTTPException

import src.core.runtime_manager as rm
from src.core.state_machine import InvalidStateTransition, ReconciliationState
from src.schemas.preprocessing import (
    NormalizationEntrySchema,
    NormalizationSummary,
    PreprocessingResponse,
)
from src.schemas.intake import SnapshotInfo
from src.services.vendor_normalization import run_normalization

router = APIRouter(prefix="/reconciliation", tags=["preprocessing"])


@router.post("/{session_id}/preprocess", response_model=PreprocessingResponse)
def run_preprocess(session_id: str):
    """
    Run vendor normalization and advance session from 'profiled' to 'preprocessed'.

    Returns 409 with a specific "no recomputation" message if already preprocessed.
    Returns 409 if session is in any other non-profiled state.
    """
    # --- Guard: session existence ---
    if not rm.session_exists(session_id):
        raise HTTPException(status_code=404, detail=f"Session not found: {session_id}")

    current = rm.get_current_state(session_id)

    # --- Guard: already preprocessed (explicit, distinct from generic wrong-state) ---
    if current == ReconciliationState.PREPROCESSED:
        raise HTTPException(
            status_code=409,
            detail=(
                "Session is already in 'preprocessed' state. "
                "No recomputation is permitted once preprocessing is complete."
            ),
        )

    # --- Guard: correct pre-condition state ---
    if current != ReconciliationState.PROFILED:
        raise HTTPException(
            status_code=409,
            detail=(
                f"Preprocessing requires state 'profiled'. "
                f"Current state is '{current.value}'."
            ),
        )

    # --- Pull inputs from runtime ---
    runtime = rm.get_runtime(session_id)
    config  = runtime["config"]

    gl_df  = runtime["raw_data"]["gl"]
    sub_df = runtime["raw_data"]["subledger"]

    nlp_threshold = config.get("vendor_nlp_threshold", 0.90)
    alias_map     = config.get("alias_map", {})
    alias_version = config.get("alias_version", "v1.0.0")

    # --- Run normalization pipeline (pure, no side effects) ---
    try:
        result = run_normalization(
            gl_df=         gl_df,
            sub_df=        sub_df,
            nlp_threshold= nlp_threshold,
            alias_map=     alias_map,
            alias_version= alias_version,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    # --- Write results BEFORE state advance so snapshot captures everything ---
    rm.write_vendor_normalization_map(session_id, result.to_map_list())

    rm.write_clean_data(session_id, {
        "gl":       result.gl_df,
        "subledger": result.sub_df,
    })

    rm.write_preprocessing(session_id, {
        "threshold_used":       result.threshold_used,
        "alias_version":        result.alias_version,
        "tier1_count":          result.tier1_count,
        "tier2_count":          result.tier2_count,
        "tier3_count":          result.tier3_count,
        "total_gl_vendors":     len(result.entries),
    })

    # --- Advance state (snapshot fires automatically) ---
    try:
        rm.advance_state(
            session_id,
            ReconciliationState.PREPROCESSED,
            triggered_by="preprocess",
        )
    except InvalidStateTransition as exc:
        raise HTTPException(status_code=409, detail=str(exc))

    # --- Build response ---
    snapshots = rm.get_session_snapshots(session_id)
    latest    = snapshots[-1] if snapshots else {}

    return PreprocessingResponse(
        session_id=session_id,
        state=rm.get_current_state(session_id).value,
        normalization_summary=NormalizationSummary(
            total_unique_gl_vendors=len(result.entries),
            tier1_count=            result.tier1_count,
            tier2_count=            result.tier2_count,
            tier3_count=            result.tier3_count,
            threshold_used=         result.threshold_used,
            alias_version=          result.alias_version,
        ),
        vendor_normalization_map=[
            NormalizationEntrySchema(**e.to_dict()) for e in result.entries
        ],
        snapshot=SnapshotInfo(
            key=             latest.get("pre_transition_state", ""),
            integrity_hash=  latest.get("integrity_hash", ""),
        ),
    )
