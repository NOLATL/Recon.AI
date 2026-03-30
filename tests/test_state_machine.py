"""
Tests for state_machine.py — transition enforcement, review phase guard,
snapshot capture, and RuntimeManager integration.
"""

import pytest

from src.core.state_machine import (
    ReconciliationState,
    StateManager,
    ALLOWED_TRANSITIONS,
    REVIEW_STATES,
    validate_transition,
    InvalidStateTransition,
    ReviewPhaseViolation,
    TerminalStateError,
)
from src.core.runtime import create_runtime
from src.core.snapshot import list_snapshots
import src.core.runtime_manager as rm


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_runtime(state: str = "initialized") -> dict:
    runtime = create_runtime("test-session")
    runtime["current_state"] = state
    return runtime


def _make_sm(state: str = "initialized") -> StateManager:
    return StateManager(_make_runtime(state))


# ---------------------------------------------------------------------------
# validate_transition — pure function tests
# ---------------------------------------------------------------------------

class TestValidateTransition:
    def test_valid_first_transition(self):
        validate_transition(
            ReconciliationState.INITIALIZED,
            ReconciliationState.FILES_LOADED,
        )  # must not raise

    def test_valid_full_chain(self):
        """Every consecutive pair in the full happy path must be legal."""
        states = list(ALLOWED_TRANSITIONS.keys())
        for i in range(len(states) - 1):
            current = states[i]
            targets = ALLOWED_TRANSITIONS[current]
            if targets:
                validate_transition(current, targets[0])  # must not raise

    def test_backward_transition_raises(self):
        with pytest.raises(InvalidStateTransition):
            validate_transition(
                ReconciliationState.FILES_LOADED,
                ReconciliationState.INITIALIZED,
            )

    def test_skip_transition_raises(self):
        """Skipping a state is illegal even if it is 'forward'."""
        with pytest.raises(InvalidStateTransition):
            validate_transition(
                ReconciliationState.INITIALIZED,
                ReconciliationState.PREPROCESSED,
            )

    def test_same_state_transition_raises(self):
        """Re-entering the same state is illegal."""
        with pytest.raises(InvalidStateTransition):
            validate_transition(
                ReconciliationState.PROFILED,
                ReconciliationState.PROFILED,
            )

    def test_terminal_state_raises_terminal_error(self):
        with pytest.raises(TerminalStateError):
            validate_transition(
                ReconciliationState.FINALIZED,
                ReconciliationState.FINALIZED,
            )


# ---------------------------------------------------------------------------
# StateManager — transition mechanics
# ---------------------------------------------------------------------------

class TestStateManagerTransition:
    def test_initial_state_is_initialized(self):
        sm = _make_sm()
        assert sm.current_state == ReconciliationState.INITIALIZED

    def test_valid_transition_advances_state(self):
        sm = _make_sm()
        sm.transition(ReconciliationState.FILES_LOADED)
        assert sm.current_state == ReconciliationState.FILES_LOADED

    def test_transition_updates_runtime_dict(self):
        runtime = _make_runtime()
        sm = StateManager(runtime)
        sm.transition(ReconciliationState.FILES_LOADED)
        assert runtime["current_state"] == "files_loaded"

    def test_illegal_transition_raises_and_does_not_mutate(self):
        sm = _make_sm("initialized")
        original_state = sm.current_state
        with pytest.raises(InvalidStateTransition):
            sm.transition(ReconciliationState.PREPROCESSED)
        assert sm.current_state == original_state

    def test_backward_transition_raises_and_does_not_mutate(self):
        sm = _make_sm("files_loaded")
        with pytest.raises(InvalidStateTransition):
            sm.transition(ReconciliationState.INITIALIZED)
        assert sm.current_state == ReconciliationState.FILES_LOADED

    def test_snapshot_written_before_transition(self):
        runtime = _make_runtime()
        sm = StateManager(runtime)
        assert len(list_snapshots(runtime)) == 0

        sm.transition(ReconciliationState.FILES_LOADED)

        snapshots = list_snapshots(runtime)
        assert len(snapshots) == 1
        snap = snapshots[0]
        assert snap["pre_transition_state"] == "initialized"

    def test_snapshot_captured_for_every_transition(self):
        runtime = _make_runtime()
        sm = StateManager(runtime)

        sm.transition(ReconciliationState.FILES_LOADED)
        sm.transition(ReconciliationState.COLUMN_MAPPING_COMPLETE)
        sm.transition(ReconciliationState.PROFILED)
        sm.transition(ReconciliationState.PREPROCESSED)

        assert len(list_snapshots(runtime)) == 4

    def test_snapshot_integrity_hash_present(self):
        runtime = _make_runtime()
        sm = StateManager(runtime)
        sm.transition(ReconciliationState.FILES_LOADED)
        snap = list_snapshots(runtime)[0]
        assert "integrity_hash" in snap
        assert len(snap["integrity_hash"]) == 64  # SHA-256 hex

    def test_triggered_by_recorded_in_snapshot(self):
        runtime = _make_runtime()
        sm = StateManager(runtime)
        sm.transition(ReconciliationState.FILES_LOADED, triggered_by="user:alice")
        snap = list_snapshots(runtime)[0]
        assert snap["triggered_by"] == "user:alice"


# ---------------------------------------------------------------------------
# StateManager — review phase guard
# ---------------------------------------------------------------------------

class TestReviewPhaseGuard:
    @pytest.mark.parametrize("review_state", [
        "deterministic_complete",
        "probabilistic_complete",
        "ai_suggested",
    ])
    def test_assert_not_in_review_raises_during_review(self, review_state):
        sm = _make_sm(review_state)
        with pytest.raises(ReviewPhaseViolation):
            sm.assert_not_in_review()

    @pytest.mark.parametrize("non_review_state", [
        "initialized",
        "files_loaded",
        "preprocessed",
        "deterministic_review_complete",
        "ai_review_complete",
        "finalized",
    ])
    def test_assert_not_in_review_passes_outside_review(self, non_review_state):
        sm = _make_sm(non_review_state)
        sm.assert_not_in_review()  # must not raise

    def test_is_review_phase_true_in_review(self):
        sm = _make_sm("deterministic_complete")
        assert sm.is_review_phase() is True

    def test_is_review_phase_false_outside_review(self):
        sm = _make_sm("preprocessed")
        assert sm.is_review_phase() is False


# ---------------------------------------------------------------------------
# RuntimeManager — integration tests
# ---------------------------------------------------------------------------

class TestRuntimeManager:
    def test_create_session_returns_id(self):
        session_id = rm.create_session()
        assert isinstance(session_id, str)
        assert len(session_id) == 36  # UUID format

    def test_session_starts_in_initialized(self):
        session_id = rm.create_session()
        assert rm.get_current_state(session_id) == ReconciliationState.INITIALIZED

    def test_advance_state_valid(self):
        session_id = rm.create_session()
        new_state = rm.advance_state(session_id, ReconciliationState.FILES_LOADED)
        assert new_state == ReconciliationState.FILES_LOADED

    def test_advance_state_illegal_raises(self):
        session_id = rm.create_session()
        with pytest.raises(InvalidStateTransition):
            rm.advance_state(session_id, ReconciliationState.FINALIZED)

    def test_advance_state_unknown_session_raises(self):
        with pytest.raises(KeyError):
            rm.advance_state("nonexistent-id", ReconciliationState.FILES_LOADED)

    def test_snapshot_captured_on_advance(self):
        session_id = rm.create_session()
        rm.advance_state(session_id, ReconciliationState.FILES_LOADED)
        snapshots = rm.get_session_snapshots(session_id)
        assert len(snapshots) == 1

    def test_assert_not_in_review_via_manager(self):
        session_id = rm.create_session()
        rm.advance_state(session_id, ReconciliationState.FILES_LOADED)
        rm.advance_state(session_id, ReconciliationState.COLUMN_MAPPING_COMPLETE)
        rm.advance_state(session_id, ReconciliationState.PROFILED)
        rm.advance_state(session_id, ReconciliationState.PREPROCESSED)
        rm.advance_state(session_id, ReconciliationState.MATCHING_CONFIGURED)
        rm.advance_state(session_id, ReconciliationState.DETERMINISTIC_COMPLETE)

        with pytest.raises(ReviewPhaseViolation):
            rm.assert_not_in_review(session_id)

    def test_get_snapshot_by_phase(self):
        session_id = rm.create_session()
        rm.advance_state(session_id, ReconciliationState.FILES_LOADED)
        snap = rm.get_session_snapshot(session_id, "initialized")
        assert snap is not None
        assert snap["pre_transition_state"] == "initialized"
