"""
Snapshot retrieval endpoints.

All snapshots are read-only. No endpoint here mutates state.
Snapshots are always returned as they were captured — they are never recomputed.
"""

from fastapi import APIRouter, HTTPException

import src.core.runtime_manager as rm
from src.exceptions import SessionNotFound, SnapshotNotFound
from src.schemas.snapshot import SnapshotDetailResponse, SnapshotListResponse, SnapshotSummary

router = APIRouter(prefix="/reconciliation", tags=["snapshots"])


@router.get("/{session_id}/snapshots", response_model=SnapshotListResponse)
def list_snapshots(session_id: str):
    """List all snapshots captured for the session, in transition order."""
    if not rm.session_exists(session_id):
        raise HTTPException(status_code=404, detail=f"Session not found: {session_id}")

    snapshots = rm.get_session_snapshots(session_id)

    summaries = [
        SnapshotSummary(
            pre_transition_state=s["pre_transition_state"],
            captured_at=s["captured_at"],
            triggered_by=s["triggered_by"],
            integrity_hash=s["integrity_hash"],
            session_id=s.get("session_id"),
        )
        for s in snapshots
    ]

    return SnapshotListResponse(
        session_id=session_id,
        snapshots=summaries,
        count=len(summaries),
    )


@router.get("/{session_id}/snapshots/{phase_name}", response_model=SnapshotDetailResponse)
def get_snapshot(session_id: str, phase_name: str):
    """
    Retrieve the full immutable snapshot for a specific phase.

    `phase_name` matches the state value at the time of capture
    (e.g., 'initialized', 'files_loaded', 'preprocessed').
    """
    if not rm.session_exists(session_id):
        raise HTTPException(status_code=404, detail=f"Session not found: {session_id}")

    snap = rm.get_session_snapshot(session_id, phase_name)
    if snap is None:
        raise HTTPException(
            status_code=404,
            detail=f"No snapshot found for phase '{phase_name}' in session '{session_id}'",
        )

    return SnapshotDetailResponse(
        pre_transition_state=snap["pre_transition_state"],
        captured_at=snap["captured_at"],
        triggered_by=snap["triggered_by"],
        integrity_hash=snap["integrity_hash"],
        session_id=snap.get("session_id"),
        runtime_snapshot=snap.get("runtime_snapshot", {}),
    )
