"""
Typed HTTP-aware exceptions for the reconciliation API.

FastAPI exception handlers in main.py map these to appropriate HTTP responses.
Route handlers should raise these; they must never return raw error dicts.
"""

from src.core.state_machine import (  # re-export for convenience
    InvalidStateTransition,
    ReviewPhaseViolation,
    TerminalStateError,
)


class SessionNotFound(Exception):
    """Raised when a session_id does not exist in the runtime store."""
    def __init__(self, session_id: str):
        super().__init__(f"Session not found: {session_id}")
        self.session_id = session_id


class SnapshotNotFound(Exception):
    """Raised when a snapshot key does not exist for the session."""
    def __init__(self, session_id: str, phase: str):
        super().__init__(f"No snapshot for phase '{phase}' in session '{session_id}'")
        self.session_id = session_id
        self.phase = phase


class FileValidationError(Exception):
    """
    Raised when one or more uploaded files fail schema validation.

    `errors` is a list of serialized FileValidationResult dicts — one per
    failing file. The list is ready to embed directly in an HTTP 422 response.
    """
    def __init__(self, errors: list):
        self.errors = errors
        file_keys = [e.get("file_key", "?") for e in errors]
        super().__init__(f"Validation failed for: {file_keys}")

    def to_detail(self) -> list:
        """Return the structured error list for the HTTP response body."""
        return self.errors


class LayerNotReady(Exception):
    """Raised when a layer endpoint is called before its required state is reached."""
    def __init__(self, layer: str, required_state: str, current_state: str):
        super().__init__(
            f"Layer '{layer}' requires state '{required_state}', "
            f"but session is in '{current_state}'."
        )
        self.layer = layer
        self.required_state = required_state
        self.current_state = current_state
