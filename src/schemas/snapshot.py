"""Pydantic v2 schemas for snapshot retrieval endpoints."""

from typing import Any, Dict, List, Optional
from pydantic import BaseModel


class SnapshotSummary(BaseModel):
    pre_transition_state: str
    captured_at: str
    triggered_by: str
    integrity_hash: str
    session_id: Optional[str] = None


class SnapshotDetailResponse(BaseModel):
    pre_transition_state: str
    captured_at: str
    triggered_by: str
    integrity_hash: str
    session_id: Optional[str]
    runtime_snapshot: Dict[str, Any]


class SnapshotListResponse(BaseModel):
    session_id: str
    snapshots: List[SnapshotSummary]
    count: int
