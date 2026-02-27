"""
Profiling endpoint — Phase 2: files_loaded → profiled

Flow:
  1. Guard: session exists
  2. Guard: state is exactly FILES_LOADED
     - If already PROFILED → specific 409 "no recomputation" message
     - Any other wrong state → generic 409
  3. Run deterministic profiling on runtime["raw_data"]
  4. Generate narrative (deterministic stub)
  5. Write profiling + narrative to runtime["profiling"] (before snapshot)
  6. Advance state to PROFILED (snapshot fires automatically inside transition)
  7. Return metrics + narrative + snapshot info

Architecture notes:
- Profiling data is written to runtime BEFORE advance_state(), so the snapshot
  captures the metrics alongside the pre-transition state (files_loaded).
- No direct dict mutation — all writes through rm.write_profiling().
- No recomputation is enforced by the state guard: once PROFILED, the endpoint
  rejects further calls with a distinct error message.
"""

from fastapi import APIRouter, HTTPException

import src.core.runtime_manager as rm
from src.core.state_machine import InvalidStateTransition, ReconciliationState
from src.schemas.profiling import (
    CrossFileSummarySchema,
    DateRangeSchema,
    FileProfilingSummary,
    NumericDistributionSchema,
    ProfilingMetrics,
    ProfilingResponse,
)
from src.schemas.intake import SnapshotInfo
from src.services.profiling_service import run_profiling
from src.services.narrative_service import generate_narrative

router = APIRouter(prefix="/reconciliation", tags=["profiling"])


def _build_metrics_schema(result) -> ProfilingMetrics:
    """Convert ProfilingResult dataclass tree into Pydantic schema instances."""
    files_out = {}
    for key, fr in result.files.items():
        files_out[key] = FileProfilingSummary(
            file_key=fr.file_key,
            row_count=fr.row_count,
            null_counts=fr.null_counts,
            null_percentages=fr.null_percentages,
            duplicate_row_count=fr.duplicate_row_count,
            numeric_distributions={
                col: NumericDistributionSchema(**nd.to_dict())
                for col, nd in fr.numeric_distributions.items()
            },
            date_ranges={
                col: DateRangeSchema(**dr.to_dict())
                for col, dr in fr.date_ranges.items()
            },
            entity_distribution=fr.entity_distribution,
        )

    return ProfilingMetrics(
        files=files_out,
        cross_file=CrossFileSummarySchema(**result.cross_file.to_dict()),
    )


@router.post("/{session_id}/profile", response_model=ProfilingResponse)
def run_profile(session_id: str):
    """
    Profile the validated datasets and advance to 'profiled' state.

    Returns 409 with a specific "no recomputation" message if already profiled.
    Returns 409 if session is in any other non-files_loaded state.
    """
    # --- Guard: session existence ---
    if not rm.session_exists(session_id):
        raise HTTPException(status_code=404, detail=f"Session not found: {session_id}")

    current = rm.get_current_state(session_id)

    # --- Guard: already profiled (explicit, distinct from generic wrong-state) ---
    if current == ReconciliationState.PROFILED:
        raise HTTPException(
            status_code=409,
            detail=(
                "Session is already in 'profiled' state. "
                "No recomputation is permitted once profiling is complete."
            ),
        )

    # --- Guard: correct pre-condition state ---
    if current != ReconciliationState.FILES_LOADED:
        raise HTTPException(
            status_code=409,
            detail=(
                f"Profiling requires state 'files_loaded'. "
                f"Current state is '{current.value}'."
            ),
        )

    # --- Compute metrics (pure, no side effects on runtime) ---
    runtime = rm.get_runtime(session_id)
    try:
        result = run_profiling(runtime["raw_data"])
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    metrics_dict = result.to_dict()

    # --- Generate narrative (deterministic stub) ---
    narrative = generate_narrative(metrics_dict)

    # --- Write profiling data BEFORE state advance ---
    # The snapshot triggered by advance_state() will capture these metrics
    # as part of the immutable pre-transition record of the files_loaded phase.
    rm.write_profiling(session_id, {
        "metrics":   metrics_dict,
        "narrative": narrative,
    })

    # --- Advance state (snapshot fires automatically) ---
    try:
        rm.advance_state(
            session_id,
            ReconciliationState.PROFILED,
            triggered_by="profile",
        )
    except InvalidStateTransition as exc:
        raise HTTPException(status_code=409, detail=str(exc))

    # --- Build response ---
    snapshots = rm.get_session_snapshots(session_id)
    latest    = snapshots[-1] if snapshots else {}

    return ProfilingResponse(
        session_id=session_id,
        state=rm.get_current_state(session_id).value,
        metrics=_build_metrics_schema(result),
        narrative=narrative,
        snapshot=SnapshotInfo(
            key=latest.get("pre_transition_state", ""),
            integrity_hash=latest.get("integrity_hash", ""),
        ),
    )
