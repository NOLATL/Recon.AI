"""Pydantic v2 schemas for column mapping discovery and confirmation."""

from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel

from src.schemas.intake import SnapshotInfo


class ColumnRole(str, Enum):
    ID       = "id"
    VENDOR   = "vendor"
    AMOUNT   = "amount"
    DATE     = "date"
    ENTITY   = "entity"
    CURRENCY = "currency"
    IGNORE   = "ignore"


class ColumnSuggestion(BaseModel):
    column_name:   str
    detected_role: Optional[ColumnRole]
    confidence:    float            # 0.0–1.0
    sample_values: List[str]        # up to 5 sample values


class SideColumnMap(BaseModel):
    id:       Optional[str] = None
    vendor:   Optional[str] = None
    amount:   Optional[str] = None
    date:     Optional[str] = None
    entity:   Optional[str] = None
    currency: Optional[str] = None


class ColumnMapConfig(BaseModel):
    side_a_label: str = "GL"
    side_b_label: str = "Subledger"
    side_a:       SideColumnMap
    side_b:       SideColumnMap


class AnalyzeColumnsResponse(BaseModel):
    session_id:           str
    state:                str
    side_a_label:         str
    side_b_label:         str
    side_a_suggestions:   List[ColumnSuggestion]
    side_b_suggestions:   List[ColumnSuggestion]
    analysis_narrative:   str       # brief AI narrative about data characteristics


class ConfirmColumnMappingRequest(BaseModel):
    column_map: ColumnMapConfig


class ConfirmColumnMappingResponse(BaseModel):
    session_id: str
    state:      str
    column_map: Dict[str, Any]
    snapshot:   SnapshotInfo
