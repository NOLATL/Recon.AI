"""
Core session management and state transition endpoints.

State advancement via this router goes through RuntimeManager exclusively —
no direct StateManager or runtime dict access is permitted here.
"""

from fastapi import APIRouter, HTTPException

import src.core.runtime_manager as rm
from src.core.state_machine import (
    ReconciliationState,
    InvalidStateTransition,
    ReviewPhaseViolation,
    TerminalStateError,
)
from src.schemas.session import (
    SessionCreateRequest,
    SessionCreateResponse,
    SessionStatusResponse,
    SessionListResponse,
)
from src.schemas.transition import TransitionRequest, TransitionResponse

router = APIRouter(prefix="/reconciliation", tags=["sessions"])


@router.post("/start", response_model=SessionCreateResponse)
def start_reconciliation(body: SessionCreateRequest = SessionCreateRequest()):
    """Create a new reconciliation session. Returns session_id in INITIALIZED state."""
    session_id = rm.create_session(metadata=body.metadata)
    return SessionCreateResponse(
        session_id=session_id,
        current_state=rm.get_current_state(session_id).value,
    )


@router.get("/sessions", response_model=SessionListResponse)
def list_sessions():
    """List all active session IDs."""
    ids = rm.list_session_ids()
    return SessionListResponse(session_ids=ids, count=len(ids))


@router.get("/{session_id}/status", response_model=SessionStatusResponse)
def get_session_status(session_id: str):
    """Return current state, review phase flag, and matching bucket counts."""
    if not rm.session_exists(session_id):
        raise HTTPException(status_code=404, detail=f"Session not found: {session_id}")

    runtime = rm.get_runtime(session_id)
    matching = runtime.get("matching", {})

    return SessionStatusResponse(
        session_id=session_id,
        current_state=rm.get_current_state(session_id).value,
        is_review_phase=rm.is_review_phase(session_id),
        snapshot_count=len(rm.get_session_snapshots(session_id)),
        matching_summary={k: len(v) for k, v in matching.items()},
    )


@router.post("/{session_id}/transition/{new_state}", response_model=TransitionResponse)
def transition_state(
    session_id: str,
    new_state: ReconciliationState,
    body: TransitionRequest = TransitionRequest(),
):
    """
    Advance a session to the next state.

    Used for manual / review-completion transitions
    (e.g., marking deterministic_review_complete after human sign-off).
    Layer execution transitions happen via /layers/* endpoints.
    """
    if not rm.session_exists(session_id):
        raise HTTPException(status_code=404, detail=f"Session not found: {session_id}")

    previous_state = rm.get_current_state(session_id).value

    try:
        rm.advance_state(session_id, new_state, triggered_by=body.triggered_by)
    except TerminalStateError as e:
        raise HTTPException(status_code=409, detail=str(e))
    except InvalidStateTransition as e:
        raise HTTPException(status_code=409, detail=str(e))

    snapshots = rm.get_session_snapshots(session_id)
    snapshot_key = snapshots[-1]["pre_transition_state"] if snapshots else ""

    return TransitionResponse(
        session_id=session_id,
        previous_state=previous_state,
        current_state=rm.get_current_state(session_id).value,
        snapshot_key=snapshot_key,
    )
