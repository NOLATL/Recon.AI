"""
Central runtime manager for the reconciliation engine.

This is the ONLY authorized entry point for:
  - Creating sessions
  - Reading session state
  - Advancing session state

Route handlers and service functions MUST interact with sessions through
this module. Direct writes to the runtime dict are prohibited outside of
transition functions invoked by RuntimeManager.advance_state().

Storage is in-memory for MVP. Replace _store with Redis/DB calls in Phase 2
by swapping the three private methods (_save, _load, _delete).
"""

import uuid
from typing import Dict, List, Optional

from src.core.runtime import create_runtime
from src.core.state_machine import (
    ReconciliationState,
    StateManager,
    InvalidStateTransition,
    ReviewPhaseViolation,
    TerminalStateError,
)
from src.core.snapshot import list_snapshots, get_snapshot


# ---------------------------------------------------------------------------
# In-memory backing store (MVP)
# Swap these three methods for Redis/DB calls in Phase 2.
# ---------------------------------------------------------------------------

_runtime_store: Dict[str, dict] = {}
_state_manager_store: Dict[str, StateManager] = {}


def _save(session_id: str, runtime: dict, sm: StateManager) -> None:
    _runtime_store[session_id] = runtime
    _state_manager_store[session_id] = sm


def _load(session_id: str) -> Optional[tuple[dict, StateManager]]:
    runtime = _runtime_store.get(session_id)
    sm = _state_manager_store.get(session_id)
    if runtime is None or sm is None:
        return None
    return runtime, sm


def _delete(session_id: str) -> None:
    _runtime_store.pop(session_id, None)
    _state_manager_store.pop(session_id, None)


# ---------------------------------------------------------------------------
# Session lifecycle
# ---------------------------------------------------------------------------

def create_session(metadata: Optional[dict] = None) -> str:
    """
    Initialize a new reconciliation session.

    Returns the session_id. The session begins in INITIALIZED state.
    """
    session_id = str(uuid.uuid4())
    runtime = create_runtime(session_id)

    if metadata:
        runtime["config"].update(metadata)

    sm = StateManager(runtime)
    _save(session_id, runtime, sm)

    return session_id


def session_exists(session_id: str) -> bool:
    return session_id in _runtime_store


def get_runtime(session_id: str) -> dict:
    """
    Return the live runtime dict for the session.

    Callers may READ from the returned dict.
    Callers must NEVER write to runtime["current_state"] directly.
    Use advance_state() for all state mutations.
    """
    result = _load(session_id)
    if result is None:
        raise KeyError(f"Session not found: {session_id}")
    runtime, _ = result
    return runtime


def get_current_state(session_id: str) -> ReconciliationState:
    result = _load(session_id)
    if result is None:
        raise KeyError(f"Session not found: {session_id}")
    _, sm = result
    return sm.current_state


def list_session_ids() -> List[str]:
    return list(_runtime_store.keys())


# ---------------------------------------------------------------------------
# State advancement (sole authorized mutation point)
# ---------------------------------------------------------------------------

def advance_state(
    session_id: str,
    target: ReconciliationState,
    triggered_by: str = "system",
) -> ReconciliationState:
    """
    The ONLY authorized way to advance a session's state.

    Internally delegates to StateManager.transition(), which:
      1. Validates the transition
      2. Captures an immutable snapshot of pre-transition state
      3. Mutates state atomically

    Returns the new current state.

    Raises:
        KeyError               — session not found
        TerminalStateError     — session is already finalized
        InvalidStateTransition — requested transition is not allowed
    """
    result = _load(session_id)
    if result is None:
        raise KeyError(f"Session not found: {session_id}")

    runtime, sm = result
    sm.transition(target, triggered_by=triggered_by)  # snapshot + mutation happen here
    return sm.current_state


# ---------------------------------------------------------------------------
# Review phase guard (call before any recomputation work)
# ---------------------------------------------------------------------------

def assert_not_in_review(session_id: str) -> None:
    """
    Raise ReviewPhaseViolation if the session is in a review phase.

    Layer services must call this before running any computation.
    """
    result = _load(session_id)
    if result is None:
        raise KeyError(f"Session not found: {session_id}")
    _, sm = result
    sm.assert_not_in_review()


def is_review_phase(session_id: str) -> bool:
    result = _load(session_id)
    if result is None:
        raise KeyError(f"Session not found: {session_id}")
    _, sm = result
    return sm.is_review_phase()


# ---------------------------------------------------------------------------
# Snapshot access (read-only)
# ---------------------------------------------------------------------------

def get_session_snapshots(session_id: str) -> list:
    runtime = get_runtime(session_id)
    return list_snapshots(runtime)


def get_session_snapshot(session_id: str, phase_name: str) -> Optional[dict]:
    runtime = get_runtime(session_id)
    return get_snapshot(runtime, phase_name)


# ---------------------------------------------------------------------------
# Runtime field writers (controlled mutations — NOT state transitions)
# These are the only other authorized ways to write to the runtime dict.
# Each must be called from a service function, never from a route handler.
# ---------------------------------------------------------------------------

def write_raw_data(session_id: str, key: str, dataframe) -> None:
    """Store a validated DataFrame into runtime['raw_data']."""
    runtime = get_runtime(session_id)
    if key not in runtime["raw_data"]:
        raise KeyError(f"Unknown raw_data key: '{key}'")
    runtime["raw_data"][key] = dataframe


def write_matching_results(session_id: str, layer: str, records: list) -> None:
    """Append matching results to the specified layer bucket."""
    runtime = get_runtime(session_id)
    if layer not in runtime["matching"]:
        raise KeyError(f"Unknown matching layer: '{layer}'")
    runtime["matching"][layer] = records


def write_vendor_normalization_map(session_id: str, norm_map: list) -> None:
    runtime = get_runtime(session_id)
    runtime["vendor_normalization_map"] = norm_map


def write_profiling(session_id: str, profiling_data: dict) -> None:
    runtime = get_runtime(session_id)
    runtime["profiling"] = profiling_data


def write_clean_data(session_id: str, clean_data: dict) -> None:
    runtime = get_runtime(session_id)
    runtime["clean_data"] = clean_data


def write_residual_pool(session_id: str, residual: dict) -> None:
    runtime = get_runtime(session_id)
    runtime["residual_pool"] = residual


def write_preprocessing(session_id: str, preprocessing_data: dict) -> None:
    """Store preprocessing metadata (threshold used, alias version, tier counts)."""
    runtime = get_runtime(session_id)
    runtime["preprocessing"] = preprocessing_data


def write_probabilistic(session_id: str, probabilistic_data: dict) -> None:
    """Store probabilistic metadata (threshold used, weights used, match count)."""
    runtime = get_runtime(session_id)
    runtime["probabilistic"] = probabilistic_data


def write_ai_suggested_meta(session_id: str, ai_meta: dict) -> None:
    """Store AI suggestion metadata (model_used, prompt_version, suggestion_count)."""
    runtime = get_runtime(session_id)
    runtime["ai_suggested_meta"] = ai_meta


def write_consolidation(session_id: str, consolidation_data: dict) -> None:
    """Store final consolidation summary metrics."""
    runtime = get_runtime(session_id)
    runtime["consolidation"] = consolidation_data


def write_manual_overrides(session_id: str, overrides: dict) -> None:
    """Store manual GL↔Sub override links ({gl_id: [sub_id, ...], ...})."""
    runtime = get_runtime(session_id)
    runtime["manual_overrides"] = overrides


def write_export_meta(session_id: str, export_data: dict) -> None:
    """Store export metadata (file paths, hashes, timestamp)."""
    runtime = get_runtime(session_id)
    runtime["export"] = export_data
