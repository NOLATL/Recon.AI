"""
Pydantic response schemas for Phase 8 — Final Output.
"""

from typing import List

from pydantic import BaseModel

from src.schemas.intake import SnapshotInfo


class ExportFile(BaseModel):
    """Metadata for one exported file."""
    filename:   str
    path:       str   # local file path (MVP); swap for blob URL in production
    sha256:     str   # hex digest of file content
    size_bytes: int


class ExportResponse(BaseModel):
    """Response body for POST /{session_id}/export."""
    session_id:  str
    state:       str
    export_dir:  str
    exported_at: str   # ISO-8601 UTC timestamp
    files:       List[ExportFile]
    snapshot:    SnapshotInfo
