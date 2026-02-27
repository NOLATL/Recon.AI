"""
Snapshot utility for the reconciliation engine.

Architecture contracts:
- Every snapshot is immutable once written
- Snapshots are captured BEFORE state transitions (called by StateManager)
- DataFrames are represented as structural metadata only (row count, columns, dtypes)
  to keep snapshots lightweight and JSON-serializable
- Each snapshot includes a SHA-256 integrity hash over its serializable content
- Snapshots are stored keyed by (phase_name, sequence_number) to handle reruns
"""

import copy
import hashlib
import json
from datetime import datetime, timezone
from typing import Any, Dict


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _extract_dataframe_meta(df: Any) -> Dict[str, Any]:
    """
    Return lightweight structural metadata for a DataFrame.
    Never stores the actual row data in a snapshot.
    """
    try:
        return {
            "row_count": len(df),
            "columns": list(df.columns),
            "dtypes": {col: str(dtype) for col, dtype in df.dtypes.items()},
        }
    except Exception:
        return {"row_count": None, "columns": [], "dtypes": {}}


def _sanitize_for_snapshot(value: Any) -> Any:
    """
    Recursively replace non-serializable objects (e.g. DataFrames, sets)
    with a serializable representation.
    """
    # pandas DataFrame / Series
    try:
        import pandas as pd
        if isinstance(value, pd.DataFrame):
            return _extract_dataframe_meta(value)
        if isinstance(value, pd.Series):
            return {"type": "Series", "length": len(value)}
    except ImportError:
        pass

    if isinstance(value, dict):
        return {k: _sanitize_for_snapshot(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_sanitize_for_snapshot(item) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value

    # Fallback: represent as type name
    return f"<non-serializable: {type(value).__name__}>"


def _compute_integrity_hash(payload: Dict[str, Any]) -> str:
    """SHA-256 hash of the canonically-serialized payload."""
    serialized = json.dumps(payload, sort_keys=True, default=str).encode("utf-8")
    return hashlib.sha256(serialized).hexdigest()


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def capture_snapshot(
    runtime: dict,
    pre_transition_state: str,
    triggered_by: str = "system",
) -> dict:
    """
    Create an immutable snapshot of the runtime before a state transition.

    Called exclusively by StateManager.transition() — never call directly
    from route handlers or service functions.

    The snapshot is stored inside runtime["snapshots"] keyed by phase name.
    If a key already exists (e.g. rerunning in tests), the entry is
    suffixed with a sequence counter to preserve the prior snapshot.

    Returns the snapshot dict (callers may inspect it; they must not mutate it).
    """
    timestamp = datetime.now(timezone.utc).isoformat()

    # Deep-copy then sanitize: produce a serializable representation of state
    sanitized = _sanitize_for_snapshot(copy.deepcopy(runtime))

    # Remove snapshots from the payload itself (no recursive nesting)
    sanitized.pop("snapshots", None)

    payload: Dict[str, Any] = {
        "session_id": runtime.get("session_id"),
        "pre_transition_state": pre_transition_state,
        "triggered_by": triggered_by,
        "captured_at": timestamp,
        "runtime_snapshot": sanitized,
    }

    integrity_hash = _compute_integrity_hash(payload)
    payload["integrity_hash"] = integrity_hash

    # Key collision guard — preserve earlier snapshot under a suffixed key
    snapshots: dict = runtime.setdefault("snapshots", {})
    key = pre_transition_state
    if key in snapshots:
        seq = 1
        while f"{key}_{seq}" in snapshots:
            seq += 1
        key = f"{key}_{seq}"

    snapshots[key] = payload
    return payload


def get_snapshot(runtime: dict, phase_name: str) -> dict | None:
    """Retrieve a snapshot by phase name. Returns None if not found."""
    return runtime.get("snapshots", {}).get(phase_name)


def list_snapshots(runtime: dict) -> list[dict]:
    """Return all snapshots in capture order (dict preserves insertion order in Python 3.7+)."""
    return list(runtime.get("snapshots", {}).values())
