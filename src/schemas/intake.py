"""Pydantic v2 response schemas for the file intake endpoint."""

from typing import Any, Dict, List
from pydantic import BaseModel


class ColumnErrorSchema(BaseModel):
    column: str
    expected_dtype: str
    failing_row_count: int
    failing_row_indices: List[int]
    sample_bad_values: List[str]


class FileValidationSummary(BaseModel):
    """Per-file validation result included in the success response."""
    file_key: str
    is_valid: bool
    row_count: int
    columns_validated: List[str]
    schema_hash: str


class SnapshotInfo(BaseModel):
    key: str
    integrity_hash: str


class UploadSuccessResponse(BaseModel):
    session_id: str
    state: str
    row_counts: Dict[str, int]
    validation: Dict[str, FileValidationSummary]
    snapshot: SnapshotInfo
