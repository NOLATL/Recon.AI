"""
File intake endpoint — Phase 1: initialized → files_loaded

Flow:
  1. Guard: session exists and is in INITIALIZED state
  2. Validate all three CSV files (strict, row-level, exhaustive)
  3. On validation failure → 422 with per-file, per-column error detail
  4. Write validated DataFrames via controlled runtime write functions
  5. Advance state to FILES_LOADED (snapshot fires automatically inside transition)
  6. Return row counts, schema hashes, and snapshot metadata

Architecture notes:
- Data writes use rm.write_raw_data() — no direct dict mutation
- State advance uses rm.advance_state() — snapshot created inside StateManager.transition()
- FileValidationError carries structured data; serialized directly into 422 response
"""

from typing import Optional

import pandas as pd
from fastapi import APIRouter, File, HTTPException, UploadFile

import src.core.runtime_manager as rm
from src.core.state_machine import InvalidStateTransition, ReconciliationState
from src.exceptions import FileValidationError
from src.schemas.intake import FileValidationSummary, SnapshotInfo, UploadSuccessResponse
from src.services.intake_service import validate_and_load

router = APIRouter(prefix="/reconciliation", tags=["intake"])


@router.post("/{session_id}/upload", response_model=UploadSuccessResponse)
async def upload_files(
    session_id: str,
    gl: UploadFile = File(...),
    subledger: UploadFile = File(...),
    chart_of_accounts: Optional[UploadFile] = File(None),
):
    """
    Accept Chart_of_Accounts.csv, GL.csv, Subledger.csv and advance the session
    from 'initialized' to 'files_loaded'.

    Returns 422 with structured per-column errors if any file fails validation.
    Returns 409 if the session is not in the 'initialized' state.
    """
    # --- Guard: session existence ---
    if not rm.session_exists(session_id):
        raise HTTPException(status_code=404, detail=f"Session not found: {session_id}")

    # --- Guard: correct state ---
    current = rm.get_current_state(session_id)
    if current != ReconciliationState.INITIALIZED:
        raise HTTPException(
            status_code=409,
            detail=(
                f"Upload requires state 'initialized'. "
                f"Current state is '{current.value}'."
            ),
        )

    # --- Validate uploaded files (CoA is optional) ---
    files_dict = {"gl": gl, "subledger": subledger}
    if chart_of_accounts is not None:
        files_dict["chart_of_accounts"] = chart_of_accounts

    try:
        intake = validate_and_load(files_dict)
    except FileValidationError as exc:
        raise HTTPException(status_code=422, detail=exc.to_detail())
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    # --- Write validated DataFrames ---
    for key, df in intake.dataframes.items():
        rm.write_raw_data(session_id, key, df)

    # If CoA was not provided, store an empty DataFrame with the correct schema
    if chart_of_accounts is None:
        empty_coa = pd.DataFrame(columns=[
            "account_code", "account_name", "account_type", "materiality_threshold"
        ])
        rm.write_raw_data(session_id, "chart_of_accounts", empty_coa)

    # --- Advance state (snapshot fires automatically inside StateManager.transition) ---
    # The snapshot captures: raw_data structure, config, matching buckets, etc.
    # at the moment just before the state changes to files_loaded.
    try:
        rm.advance_state(
            session_id,
            ReconciliationState.FILES_LOADED,
            triggered_by="upload",
        )
    except InvalidStateTransition as exc:
        raise HTTPException(status_code=409, detail=str(exc))

    # --- Build response ---
    snapshots = rm.get_session_snapshots(session_id)
    latest = snapshots[-1] if snapshots else {}

    validation_summary = {
        key: FileValidationSummary(
            file_key=result.file_key,
            is_valid=result.is_valid,
            row_count=result.row_count,
            columns_validated=result.columns_validated,
            schema_hash=result.schema_hash,
        )
        for key, result in intake.validation_results.items()
    }

    return UploadSuccessResponse(
        session_id=session_id,
        state=rm.get_current_state(session_id).value,
        row_counts=intake.row_counts,
        validation=validation_summary,
        snapshot=SnapshotInfo(
            key=latest.get("pre_transition_state", ""),
            integrity_hash=latest.get("integrity_hash", ""),
        ),
    )
