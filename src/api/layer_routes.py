"""
Layer execution endpoints.

Each layer endpoint:
  - Validates session state before dispatching
  - Delegates ALL computation and state advancement to the layer service
  - Never mutates state directly

Layer authority:
  - deterministic → AUTHORITATIVE
  - probabilistic → ADDITIVE
  - ai_advisory   → ADVISORY ONLY (human review required before results are applied)
"""

from fastapi import APIRouter, HTTPException

import src.core.runtime_manager as rm
from src.core.state_machine import (
    ReconciliationState,
    InvalidStateTransition,
    ReviewPhaseViolation,
)
import src.layers.deterministic as det_layer
import src.layers.probabilistic as prob_layer
import src.layers.ai_advisory as ai_layer

router = APIRouter(prefix="/reconciliation", tags=["layers"])


# ---------------------------------------------------------------------------
# Deterministic layer
# ---------------------------------------------------------------------------

@router.post("/{session_id}/layers/deterministic")
def run_deterministic(session_id: str, triggered_by: str = "system"):
    """
    Run the deterministic matching layer.

    Required pre-state: preprocessed
    Advances to:        deterministic_complete
    """
    if not rm.session_exists(session_id):
        raise HTTPException(status_code=404, detail=f"Session not found: {session_id}")

    current = rm.get_current_state(session_id)
    if current != ReconciliationState.PREPROCESSED:
        raise HTTPException(
            status_code=409,
            detail=f"Deterministic layer requires state 'preprocessed'. Current: '{current.value}'",
        )

    try:
        result = det_layer.run(session_id, triggered_by=triggered_by)
    except ReviewPhaseViolation as e:
        raise HTTPException(status_code=409, detail=str(e))
    except InvalidStateTransition as e:
        raise HTTPException(status_code=409, detail=str(e))

    return result


# ---------------------------------------------------------------------------
# Probabilistic layer
# ---------------------------------------------------------------------------

@router.post("/{session_id}/layers/probabilistic")
def run_probabilistic(session_id: str, triggered_by: str = "system"):
    """
    Run the probabilistic (fuzzy) matching layer on the residual pool.

    Required pre-state: deterministic_review_complete
    Advances to:        probabilistic_complete
    """
    if not rm.session_exists(session_id):
        raise HTTPException(status_code=404, detail=f"Session not found: {session_id}")

    current = rm.get_current_state(session_id)
    if current != ReconciliationState.DETERMINISTIC_REVIEW_COMPLETE:
        raise HTTPException(
            status_code=409,
            detail=f"Probabilistic layer requires state 'deterministic_review_complete'. Current: '{current.value}'",
        )

    try:
        result = prob_layer.run(session_id, triggered_by=triggered_by)
    except ReviewPhaseViolation as e:
        raise HTTPException(status_code=409, detail=str(e))
    except InvalidStateTransition as e:
        raise HTTPException(status_code=409, detail=str(e))

    return result


# ---------------------------------------------------------------------------
# AI advisory layer
# ---------------------------------------------------------------------------

@router.post("/{session_id}/layers/ai-advisory")
def run_ai_advisory(session_id: str, triggered_by: str = "system"):
    """
    Run the AI advisory layer on remaining unmatched records.

    Required pre-state: probabilistic_review_complete
    Advances to:        ai_suggested

    Results are ADVISORY ONLY. Human review is required before any suggestion
    is promoted to a final match.
    """
    if not rm.session_exists(session_id):
        raise HTTPException(status_code=404, detail=f"Session not found: {session_id}")

    current = rm.get_current_state(session_id)
    if current != ReconciliationState.PROBABILISTIC_REVIEW_COMPLETE:
        raise HTTPException(
            status_code=409,
            detail=f"AI advisory layer requires state 'probabilistic_review_complete'. Current: '{current.value}'",
        )

    try:
        result = ai_layer.run(session_id, triggered_by=triggered_by)
    except ReviewPhaseViolation as e:
        raise HTTPException(status_code=409, detail=str(e))
    except InvalidStateTransition as e:
        raise HTTPException(status_code=409, detail=str(e))

    return result
