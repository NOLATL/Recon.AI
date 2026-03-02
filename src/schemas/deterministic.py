"""Pydantic v2 response schemas for the deterministic matching endpoint."""

from typing import Any, Dict, List

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


class ScenarioAmountSummary(BaseModel):
    """Dollar amounts totalled for one deterministic scenario."""
    scenario_id:      int
    match_count:      int
    total_gl_amount:  float
    total_sub_amount: float


class DeterministicSummary(BaseModel):
    total_gl_records:          int
    total_sub_records:         int
    matched_gl_records:        int
    matched_sub_records:       int
    unmatched_gl_records:      int
    unmatched_sub_records:     int
    match_count:               int
    scenario_counts:           Dict[int, int]
    # Dollar totals across all matched records
    total_matched_gl_amount:   float
    total_matched_sub_amount:  float
    # Per-scenario dollar breakdown
    scenario_amount_summaries: List[ScenarioAmountSummary]


class DeterministicResponse(BaseModel):
    session_id:           str
    state:                str
    summary:              DeterministicSummary
    matches:              List[MatchRecordSchema]
    # Full input DataFrames (clean_data after vendor normalisation)
    gl_records:           List[Dict[str, Any]]
    sub_records:          List[Dict[str, Any]]
    # Residual (unmatched) rows forwarded to probabilistic pool
    residual_gl_records:  List[Dict[str, Any]]
    residual_sub_records: List[Dict[str, Any]]
    snapshot:             SnapshotInfo


class DeterministicReviewResponse(BaseModel):
    session_id:                str
    state:                     str
    deterministic_match_count: int
    residual_gl_count:         int
    residual_sub_count:        int
    snapshot:                  SnapshotInfo
