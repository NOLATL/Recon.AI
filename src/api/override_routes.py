"""
Override endpoint — stores manual GL↔Sub match overrides.

Overrides are stored in runtime["manual_overrides"] as {gl_id: [sub_id, ...]}.
They are included in final_results.csv as source_layer="manual" at export time.
Idempotent — each POST replaces any previously stored overrides for the session.
"""

from typing import Dict, List

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

import src.core.runtime_manager as rm
from src.core.state_machine import ReconciliationState

router = APIRouter(prefix="/reconciliation", tags=["overrides"])


class ManualOverridesRequest(BaseModel):
    overrides: Dict[str, List[str]]


@router.post("/{session_id}/overrides")
def save_manual_overrides(session_id: str, body: ManualOverridesRequest):
    """
    Persist manual GL↔Sub override links for this session.

    Body: {"overrides": {"GL001": ["SUB001", "SUB002"], "GL003": ["SUB005"]}}

    Idempotent — replaces any previously stored overrides.
    Not allowed once the session is FINALIZED (export already ran).
    """
    if not rm.session_exists(session_id):
        raise HTTPException(status_code=404, detail=f"Session not found: {session_id}")

    current = rm.get_current_state(session_id)
    if current == ReconciliationState.FINALIZED:
        raise HTTPException(
            status_code=409,
            detail="Cannot modify overrides on a finalized session.",
        )

    # Strip empty sub-ID lists so the export service only processes real links.
    clean = {
        gl_id: [s for s in sub_ids if s.strip()]
        for gl_id, sub_ids in body.overrides.items()
        if any(s.strip() for s in sub_ids)
    }

    rm.write_manual_overrides(session_id, clean)

    return {
        "session_id":     session_id,
        "override_count": len(clean),
        "status":         "saved",
    }


@router.get("/{session_id}/overrides")
def get_manual_overrides(session_id: str):
    """Return the currently stored manual overrides for the session."""
    if not rm.session_exists(session_id):
        raise HTTPException(status_code=404, detail=f"Session not found: {session_id}")

    runtime = rm.get_runtime(session_id)
    overrides = runtime.get("manual_overrides", {})

    return {
        "session_id":     session_id,
        "override_count": len(overrides),
        "overrides":      overrides,
    }
