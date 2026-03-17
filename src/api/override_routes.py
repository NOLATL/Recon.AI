"""
Override endpoint — stores manual GL↔Sub match overrides and manual rejections.

Overrides are stored in runtime["manual_overrides"] as {gl_id: [sub_id, ...]}.
They are included in final_results.csv as source_layer="manual" at export time.

Manual rejections are stored in runtime["manual_rejected"] as a list of
{match_id, record_ids_A, record_ids_B} dicts. They are included in
rejected_matches.csv and their GL/Sub records appear in the residual CSVs
(unless subsequently resolved via manual_overrides).

Both are idempotent — each POST replaces previously stored data.
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


class ManualRejectedItem(BaseModel):
    match_id: str
    record_ids_A: List[str]
    record_ids_B: List[str]


class ManualRejectedRequest(BaseModel):
    manual_rejected: List[ManualRejectedItem]


@router.post("/{session_id}/manual-rejected")
def save_manual_rejected(session_id: str, body: ManualRejectedRequest):
    """
    Persist matches the user manually rejected on the Matched Analysis page.

    Body: {"manual_rejected": [{"match_id": "m1", "record_ids_A": ["GL1"], "record_ids_B": ["SUB1"]}, ...]}

    These are appended to rejected_matches.csv at export time. Their GL/Sub
    records also appear in the residual unmatched CSVs unless subsequently
    resolved via a manual override link. Idempotent — replaces prior data.
    Not allowed once the session is FINALIZED.
    """
    if not rm.session_exists(session_id):
        raise HTTPException(status_code=404, detail=f"Session not found: {session_id}")

    current = rm.get_current_state(session_id)
    if current == ReconciliationState.FINALIZED:
        raise HTTPException(
            status_code=409,
            detail="Cannot modify rejected matches on a finalized session.",
        )

    payload = [item.model_dump() for item in body.manual_rejected]
    rm.write_manual_rejected(session_id, payload)

    return {
        "session_id":     session_id,
        "rejected_count": len(payload),
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
