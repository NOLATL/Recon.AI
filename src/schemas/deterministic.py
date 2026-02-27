"""Pydantic v2 response schemas for the deterministic matching endpoint."""

from typing import Dict, List

from pydantic import BaseModel

from src.schemas.intake import SnapshotInfo


class MatchRecordSchema(BaseModel):
    match_id:             str
    record_ids_A:         List[str]
    record_ids_B:         List[str]
    scenario_id:          int
    scenario_description: str
    confidence_score:     float
    grouping_type:        str
    user_status:          str
    override_flag:        bool


class DeterministicSummary(BaseModel):
    total_gl_records:    int
    total_sub_records:   int
    matched_gl_records:  int
    matched_sub_records: int
    unmatched_gl_records: int
    unmatched_sub_records: int
    match_count:         int
    scenario_counts:     Dict[int, int]


class DeterministicResponse(BaseModel):
    session_id: str
    state:      str
    summary:    DeterministicSummary
    matches:    List[MatchRecordSchema]
    snapshot:   SnapshotInfo


class DeterministicReviewResponse(BaseModel):
    session_id:                str
    state:                     str
    deterministic_match_count: int
    residual_gl_count:         int
    residual_sub_count:        int
    snapshot:                  SnapshotInfo
