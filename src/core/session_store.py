from typing import Dict
from src.core.runtime import create_runtime
from src.core.state_machine import StateManager, ReconciliationState
import uuid

_sessions: Dict[str, dict] = {}
_state_managers: Dict[str, StateManager] = {}


def create_session():
    session_id = str(uuid.uuid4())
    runtime = create_runtime(session_id)
    state_manager = StateManager(ReconciliationState.INITIALIZED)

    _sessions[session_id] = runtime
    _state_managers[session_id] = state_manager

    return session_id


def get_runtime(session_id: str):
    return _sessions.get(session_id)


def get_state_manager(session_id: str):
    return _state_managers.get(session_id)