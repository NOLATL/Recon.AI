"""Pydantic v2 response schemas for the AI suggested matches and review endpoints."""

from typing import Any, Dict, List, Literal

from pydantic import BaseModel

from src.schemas.intake import SnapshotInfo


class AIMatchSchema(BaseModel):
    match_id:            str
    record_ids_A:        List[str]
    record_ids_B:        List[str]
    ai_confidence_score: float
    materiality:         float
    supporting_features: Dict[str, Any]
    reasoning_narrative: str
    grouping_type:       str
    user_status:         str
    override_flag:       bool


class AISummary(BaseModel):
    total_residual_gl:   int
    total_residual_sub:  int
    suggestion_count:    int
    model_used:          str
    prompt_version:      str


class AIResponse(BaseModel):
    session_id:  str
    state:       str
    summary:     AISummary
    suggestions: List[AIMatchSchema]
    snapshot:    SnapshotInfo


# ---------------------------------------------------------------------------
# Phase 6A — AI Review
# ---------------------------------------------------------------------------

class AIMatchDecision(BaseModel):
    match_id: str
    decision: Literal["accepted", "rejected"]


class AIReviewRequest(BaseModel):
    decisions: List[AIMatchDecision]


class AIReviewResponse(BaseModel):
    session_id:     str
    state:          str
    accepted_count: int
    rejected_count: int
    snapshot:       SnapshotInfo
