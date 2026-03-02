"""Pydantic v2 response schemas for the probabilistic matching endpoints."""

from typing import Any, Dict, List, Literal

from pydantic import BaseModel

from src.schemas.intake import SnapshotInfo


class ProbabilisticMatchSchema(BaseModel):
    match_id:          str
    record_ids_A:      List[str]
    record_ids_B:      List[str]
    final_similarity:  float
    component_scores:  Dict[str, float]
    grouping_type:     str
    user_status:       str
    override_flag:     bool


class ProbabilisticSummary(BaseModel):
    total_gl_records:    int
    total_sub_records:   int
    matched_gl_records:  int
    matched_sub_records: int
    unmatched_gl_records:  int
    unmatched_sub_records: int
    match_count:         int
    threshold_used:      float
    weights_used:        Dict[str, float]


class ProbabilisticResponse(BaseModel):
    session_id:       str
    state:            str
    summary:          ProbabilisticSummary
    matches:          List[ProbabilisticMatchSchema]
    # Serialised rows for only the GL/Sub records that appear in at least one match.
    # Lets the review UI show full record detail without sending the entire residual pool.
    gl_pool_records:  List[Dict[str, Any]]
    sub_pool_records: List[Dict[str, Any]]
    snapshot:         SnapshotInfo


# ---------------------------------------------------------------------------
# Phase 5A — Probabilistic Review
# ---------------------------------------------------------------------------

class MatchDecision(BaseModel):
    match_id: str
    decision: Literal["accepted", "rejected"]


class ProbabilisticReviewRequest(BaseModel):
    decisions: List[MatchDecision]


class ProbabilisticReviewResponse(BaseModel):
    session_id:     str
    state:          str
    accepted_count: int
    rejected_count: int
    snapshot:       SnapshotInfo
