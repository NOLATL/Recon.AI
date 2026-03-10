"""Pydantic v2 response schemas for the profiling endpoint."""

from typing import Any, Dict, List, Optional
from pydantic import BaseModel

from src.schemas.intake import SnapshotInfo


class NumericDistributionSchema(BaseModel):
    min:        Optional[float]
    max:        Optional[float]
    mean:       Optional[float]
    median:     Optional[float]
    std:        Optional[float]
    sum:        Optional[float]
    null_count: int


class DateRangeSchema(BaseModel):
    min: Optional[str]
    max: Optional[str]


class FileProfilingSummary(BaseModel):
    file_key:              str
    row_count:             int
    unique_vendor_count:   int
    null_counts:           Dict[str, int]
    null_percentages:      Dict[str, float]
    duplicate_row_count:   int
    numeric_distributions: Dict[str, NumericDistributionSchema]
    date_ranges:           Dict[str, DateRangeSchema]
    entity_distribution:   Dict[str, int]
    column_profiles:       Dict[str, Any]


class CrossFileSummarySchema(BaseModel):
    gl_row_count:        int
    subledger_row_count: int
    row_count_delta:     int
    row_count_delta_pct: float


class ProfilingMetrics(BaseModel):
    files:      Dict[str, FileProfilingSummary]
    cross_file: CrossFileSummarySchema


class ProfilingResponse(BaseModel):
    session_id: str
    state:      str
    metrics:    ProfilingMetrics
    narrative:  str
    snapshot:   SnapshotInfo
