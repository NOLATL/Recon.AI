"""Pydantic v2 response schemas for the final consolidation endpoint."""

from pydantic import BaseModel

from src.schemas.intake import SnapshotInfo


class ConsolidationSummary(BaseModel):
    deterministic_match_count: int   # all deterministic matches (auto_confirmed)
    probabilistic_match_count: int   # accepted probabilistic matches only
    ai_match_count:            int   # accepted AI matches only
    total_match_count:         int   # sum of the three above
    residual_gl_count:         int   # unmatched GL records remaining
    residual_sub_count:        int   # unmatched Sub records remaining
    rejected_count:            int   # total rejected matches (all phases)
    override_count:            int   # matches with override_flag=True (v1: always 0)


class FinalConsolidationResponse(BaseModel):
    session_id: str
    state:      str
    summary:    ConsolidationSummary
    snapshot:   SnapshotInfo
