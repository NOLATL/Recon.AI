"""Pydantic v2 schemas for session lifecycle endpoints."""

from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class SessionCreateRequest(BaseModel):
    metadata: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Optional config overrides (weights, thresholds, ai_model, etc.)",
    )


class SessionCreateResponse(BaseModel):
    session_id: str
    current_state: str


class SessionStatusResponse(BaseModel):
    session_id: str
    current_state: str
    is_review_phase: bool
    snapshot_count: int
    matching_summary: Dict[str, int] = Field(
        description="Record count per matching bucket: deterministic, probabilistic, ai_suggested, final, rejected"
    )


class SessionListResponse(BaseModel):
    session_ids: List[str]
    count: int
