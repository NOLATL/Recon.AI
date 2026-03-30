"""
Chat and column-mapping endpoints.

Phase 1.5a — Column mapping:
  POST /{session_id}/analyze-columns    files_loaded → (no change)
  POST /{session_id}/confirm-columns    files_loaded → column_mapping_complete

Phase 3.5a — Matching config:
  POST /{session_id}/suggest-matching-config   preprocessed → (no change)
  POST /{session_id}/confirm-matching-config   preprocessed → matching_configured

General chat (any state ≥ files_loaded):
  POST /{session_id}/chat               (no state change)

Architecture notes:
- No business logic in this file — all logic lives in service modules.
- State guards follow the same pattern as all other route files.
- The /chat endpoint is stateless: conversation history is sent by the caller.
"""

from fastapi import APIRouter, HTTPException

import src.core.runtime_manager as rm
from src.core.state_machine import (
    InvalidStateTransition,
    ReconciliationState,
)
from src.schemas.column_mapping import (
    AnalyzeColumnsResponse,
    ConfirmColumnMappingRequest,
    ConfirmColumnMappingResponse,
)
from src.schemas.matching_config import (
    ConfirmMatchingConfigRequest,
    ConfirmMatchingConfigResponse,
    SuggestMatchingConfigResponse,
)
from src.schemas.chat import ChatRequest, ChatResponse
from src.schemas.intake import SnapshotInfo
from src.services.column_mapping_service import analyze_columns, confirm_column_mapping
from src.services.matching_config_service import suggest_matching_config, confirm_matching_config
from src.services.chat_service import chat_message

router = APIRouter(prefix="/reconciliation", tags=["chat"])

# States that are "at or after files_loaded" — allow general chat
_CHAT_ALLOWED_STATES = {
    "files_loaded", "column_mapping_complete", "profiled", "preprocessed",
    "matching_configured", "deterministic_complete", "deterministic_review_complete",
    "probabilistic_complete", "probabilistic_review_complete", "ai_suggested",
    "ai_review_complete", "final_consolidated", "finalized",
}


# ---------------------------------------------------------------------------
# Column mapping — Phase 1.5a
# ---------------------------------------------------------------------------

@router.post("/{session_id}/analyze-columns", response_model=AnalyzeColumnsResponse)
def run_analyze_columns(session_id: str):
    """
    Analyze column roles in the uploaded files using AI. Read-only, no state change.
    Requires state: files_loaded
    """
    if not rm.session_exists(session_id):
        raise HTTPException(status_code=404, detail=f"Session not found: {session_id}")

    current = rm.get_current_state(session_id)
    if current != ReconciliationState.FILES_LOADED:
        raise HTTPException(
            status_code=409,
            detail=(
                f"Column analysis requires state 'files_loaded'. "
                f"Current state is '{current.value}'."
            ),
        )

    try:
        return analyze_columns(session_id)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@router.post("/{session_id}/confirm-columns", response_model=ConfirmColumnMappingResponse)
def run_confirm_columns(session_id: str, request: ConfirmColumnMappingRequest):
    """
    Validate and persist the confirmed column mapping.
    Advances state: files_loaded → column_mapping_complete
    """
    if not rm.session_exists(session_id):
        raise HTTPException(status_code=404, detail=f"Session not found: {session_id}")

    current = rm.get_current_state(session_id)
    if current == ReconciliationState.COLUMN_MAPPING_COMPLETE:
        raise HTTPException(
            status_code=409,
            detail=(
                "Session is already in 'column_mapping_complete' state. "
                "Column mapping has already been confirmed."
            ),
        )
    if current != ReconciliationState.FILES_LOADED:
        raise HTTPException(
            status_code=409,
            detail=(
                f"Column mapping confirmation requires state 'files_loaded'. "
                f"Current state is '{current.value}'."
            ),
        )

    try:
        confirm_column_mapping(session_id, request.column_map)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except InvalidStateTransition as exc:
        raise HTTPException(status_code=409, detail=str(exc))

    runtime   = rm.get_runtime(session_id)
    snapshots = rm.get_session_snapshots(session_id)
    latest    = snapshots[-1] if snapshots else {}

    return ConfirmColumnMappingResponse(
        session_id=session_id,
        state=rm.get_current_state(session_id).value,
        column_map=runtime["config"]["column_map"],
        snapshot=SnapshotInfo(
            key=latest.get("pre_transition_state", ""),
            integrity_hash=latest.get("integrity_hash", ""),
        ),
    )


# ---------------------------------------------------------------------------
# Matching config — Phase 3.5a
# ---------------------------------------------------------------------------

@router.post("/{session_id}/suggest-matching-config", response_model=SuggestMatchingConfigResponse)
def run_suggest_matching_config(session_id: str):
    """
    AI-recommend deterministic scenarios and probabilistic weights. Read-only, no state change.
    Requires state: preprocessed
    """
    if not rm.session_exists(session_id):
        raise HTTPException(status_code=404, detail=f"Session not found: {session_id}")

    current = rm.get_current_state(session_id)
    if current != ReconciliationState.PREPROCESSED:
        raise HTTPException(
            status_code=409,
            detail=(
                f"Matching config suggestion requires state 'preprocessed'. "
                f"Current state is '{current.value}'."
            ),
        )

    try:
        return suggest_matching_config(session_id)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@router.post("/{session_id}/confirm-matching-config", response_model=ConfirmMatchingConfigResponse)
def run_confirm_matching_config(session_id: str, request: ConfirmMatchingConfigRequest):
    """
    Validate and persist the confirmed matching configuration.
    Advances state: preprocessed → matching_configured
    """
    if not rm.session_exists(session_id):
        raise HTTPException(status_code=404, detail=f"Session not found: {session_id}")

    current = rm.get_current_state(session_id)
    if current == ReconciliationState.MATCHING_CONFIGURED:
        raise HTTPException(
            status_code=409,
            detail=(
                "Session is already in 'matching_configured' state. "
                "Matching configuration has already been confirmed."
            ),
        )
    if current != ReconciliationState.PREPROCESSED:
        raise HTTPException(
            status_code=409,
            detail=(
                f"Matching config confirmation requires state 'preprocessed'. "
                f"Current state is '{current.value}'."
            ),
        )

    try:
        confirm_matching_config(session_id, request)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except InvalidStateTransition as exc:
        raise HTTPException(status_code=409, detail=str(exc))

    runtime   = rm.get_runtime(session_id)
    snapshots = rm.get_session_snapshots(session_id)
    latest    = snapshots[-1] if snapshots else {}

    return ConfirmMatchingConfigResponse(
        session_id=session_id,
        state=rm.get_current_state(session_id).value,
        matching_config=runtime["config"]["matching_config"],
        snapshot=SnapshotInfo(
            key=latest.get("pre_transition_state", ""),
            integrity_hash=latest.get("integrity_hash", ""),
        ),
    )


# ---------------------------------------------------------------------------
# Matching config — GET (read-only, any state after matching_configured)
# ---------------------------------------------------------------------------

@router.get("/{session_id}/matching-config")
def get_matching_config(session_id: str):
    """
    Return the confirmed matching config stored in the session runtime.
    Returns an empty deterministic list and empty probabilistic dict when defaults apply.
    Available in any state ≥ matching_configured (or later).
    """
    if not rm.session_exists(session_id):
        raise HTTPException(status_code=404, detail=f"Session not found: {session_id}")
    runtime = rm.get_runtime(session_id)
    return {"matching_config": runtime["config"].get("matching_config", {})}


# ---------------------------------------------------------------------------
# General chat
# ---------------------------------------------------------------------------

@router.post("/{session_id}/chat", response_model=ChatResponse)
def run_chat(session_id: str, request: ChatRequest):
    """
    General-purpose data exploration chat. No state change.
    Available in any state ≥ files_loaded.
    """
    if not rm.session_exists(session_id):
        raise HTTPException(status_code=404, detail=f"Session not found: {session_id}")

    current = rm.get_current_state(session_id)
    if current.value not in _CHAT_ALLOWED_STATES:
        raise HTTPException(
            status_code=409,
            detail=(
                f"Chat is available once files have been uploaded. "
                f"Current state is '{current.value}'."
            ),
        )

    try:
        return chat_message(session_id, request)
    except Exception as exc:
        import logging
        logging.getLogger(__name__).error("Chat route unhandled error: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=f"Chat error: {exc}")
