"""
State machine for the reconciliation engine.

Architecture contracts:
- Forward-only transitions enforced via ALLOWED_TRANSITIONS
- No backward navigation — ever
- All state mutations occur exclusively inside transition()
- Recomputation blocked during REVIEW_STATES
"""

from enum import Enum
from typing import Dict, List, Set


class ReconciliationState(str, Enum):
    INITIALIZED = "initialized"
    FILES_LOADED = "files_loaded"
    PROFILED = "profiled"
    PREPROCESSED = "preprocessed"
    DETERMINISTIC_COMPLETE = "deterministic_complete"
    DETERMINISTIC_REVIEW_COMPLETE = "deterministic_review_complete"
    PROBABILISTIC_COMPLETE = "probabilistic_complete"
    PROBABILISTIC_REVIEW_COMPLETE = "probabilistic_review_complete"
    AI_SUGGESTED = "ai_suggested"
    AI_REVIEW_COMPLETE = "ai_review_complete"
    FINAL_CONSOLIDATED = "final_consolidated"
    FINALIZED = "finalized"


# Explicit forward-only transition map — the authoritative source of truth.
# Any (from, to) pair not represented here is illegal.
ALLOWED_TRANSITIONS: Dict[ReconciliationState, List[ReconciliationState]] = {
    ReconciliationState.INITIALIZED:                    [ReconciliationState.FILES_LOADED],
    ReconciliationState.FILES_LOADED:                   [ReconciliationState.PROFILED],
    ReconciliationState.PROFILED:                       [ReconciliationState.PREPROCESSED],
    ReconciliationState.PREPROCESSED:                   [ReconciliationState.DETERMINISTIC_COMPLETE],
    ReconciliationState.DETERMINISTIC_COMPLETE:         [ReconciliationState.DETERMINISTIC_REVIEW_COMPLETE],
    ReconciliationState.DETERMINISTIC_REVIEW_COMPLETE:  [ReconciliationState.PROBABILISTIC_COMPLETE],
    ReconciliationState.PROBABILISTIC_COMPLETE:         [ReconciliationState.PROBABILISTIC_REVIEW_COMPLETE],
    ReconciliationState.PROBABILISTIC_REVIEW_COMPLETE:  [ReconciliationState.AI_SUGGESTED],
    ReconciliationState.AI_SUGGESTED:                   [ReconciliationState.AI_REVIEW_COMPLETE],
    ReconciliationState.AI_REVIEW_COMPLETE:             [ReconciliationState.FINAL_CONSOLIDATED],
    ReconciliationState.FINAL_CONSOLIDATED:             [ReconciliationState.FINALIZED],
    ReconciliationState.FINALIZED:                      [],
}

# States during which no layer recomputation is permitted.
# These are the "awaiting human review" windows.
REVIEW_STATES: Set[ReconciliationState] = {
    ReconciliationState.DETERMINISTIC_COMPLETE,
    ReconciliationState.PROBABILISTIC_COMPLETE,
    ReconciliationState.AI_SUGGESTED,
}

# States from which no further transitions are possible.
TERMINAL_STATES: Set[ReconciliationState] = {
    ReconciliationState.FINALIZED,
}


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------

class InvalidStateTransition(Exception):
    """Raised when a requested transition is not in ALLOWED_TRANSITIONS."""


class ReviewPhaseViolation(Exception):
    """Raised when recomputation or mutation is attempted during a review phase."""


class TerminalStateError(Exception):
    """Raised when a transition is attempted from a terminal state."""


# ---------------------------------------------------------------------------
# Validator (pure function — no side effects)
# ---------------------------------------------------------------------------

def validate_transition(
    current: ReconciliationState,
    target: ReconciliationState,
) -> None:
    """
    Assert that transitioning from `current` to `target` is legal.

    Raises:
        TerminalStateError     — if current is a terminal state
        InvalidStateTransition — if (current → target) is not in the map
    """
    if current in TERMINAL_STATES:
        raise TerminalStateError(
            f"Session is in terminal state '{current.value}'. No further transitions allowed."
        )

    allowed = ALLOWED_TRANSITIONS.get(current, [])
    if target not in allowed:
        raise InvalidStateTransition(
            f"Illegal transition: '{current.value}' → '{target.value}'. "
            f"Allowed next states: {[s.value for s in allowed] or 'none'}"
        )


# ---------------------------------------------------------------------------
# StateManager
# ---------------------------------------------------------------------------

class StateManager:
    """
    Owns state transitions for one reconciliation session.

    The `transition()` method is the ONLY authorized mutation point.
    Callers must never write to runtime["current_state"] directly.
    """

    def __init__(self, runtime: dict) -> None:
        self._runtime = runtime
        self.current_state: ReconciliationState = ReconciliationState(
            runtime["current_state"]
        )

    # ------------------------------------------------------------------
    # Guards (callable by API layer before starting expensive work)
    # ------------------------------------------------------------------

    def assert_not_in_review(self) -> None:
        """Raise ReviewPhaseViolation if the session is awaiting human review."""
        if self.current_state in REVIEW_STATES:
            raise ReviewPhaseViolation(
                f"Recomputation is prohibited during review phase "
                f"'{self.current_state.value}'."
            )

    def is_review_phase(self) -> bool:
        return self.current_state in REVIEW_STATES

    def is_terminal(self) -> bool:
        return self.current_state in TERMINAL_STATES

    # ------------------------------------------------------------------
    # Transition (sole mutation entry point)
    # ------------------------------------------------------------------

    def transition(
        self,
        target: ReconciliationState,
        triggered_by: str = "system",
    ) -> None:
        """
        Advance the session to `target`.

        Strict order of operations — never alter this sequence:
          1. Validate the transition is permitted (no side effects)
          2. Capture an immutable snapshot of the pre-transition state
          3. Mutate StateManager.current_state
          4. Mutate runtime["current_state"] to keep them in sync

        Raises:
            TerminalStateError, InvalidStateTransition
        """
        # Step 1 — validate before touching anything
        validate_transition(self.current_state, target)

        # Step 2 — snapshot BEFORE mutation (architecture requirement)
        from src.core.snapshot import capture_snapshot  # late import to avoid circular
        capture_snapshot(
            runtime=self._runtime,
            pre_transition_state=self.current_state.value,
            triggered_by=triggered_by,
        )

        # Steps 3 & 4 — atomic state mutation
        self.current_state = target
        self._runtime["current_state"] = target.value
