"""Pydantic v2 response schemas for the preprocessing (vendor normalization) endpoint."""

from typing import List, Optional

from pydantic import BaseModel

from src.schemas.intake import SnapshotInfo


class NormalizationEntrySchema(BaseModel):
    original_vendor:     str
    normalized_vendor:   str
    matched_to:          Optional[str]
    match_source:        str            # "preprocessing" | "nlp" | "ai"
    similarity_score:    Optional[float]
    ai_confidence_score: Optional[float]


class NormalizationSummary(BaseModel):
    total_unique_gl_vendors: int
    tier1_count:             int     # resolved by deterministic preprocessing
    tier2_count:             int     # resolved by NLP fuzzy matching
    tier3_count:             int     # unresolved — AI stub
    threshold_used:          float   # nlp_threshold value used (0.0–1.0)
    alias_version:           str     # version tag of the alias configuration


class PreprocessingResponse(BaseModel):
    session_id:              str
    state:                   str
    normalization_summary:   NormalizationSummary
    vendor_normalization_map: List[NormalizationEntrySchema]
    snapshot:                SnapshotInfo
