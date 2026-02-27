"""
Shared pytest fixtures for the reconciliation engine test suite.
"""

import pytest
from fastapi.testclient import TestClient

from src.api.main import app
import src.core.runtime_manager as rm


@pytest.fixture(autouse=True)
def clear_runtime_store():
    """
    Reset the in-memory runtime store before every test.
    Prevents state leaking between tests.
    """
    rm._runtime_store.clear()
    rm._state_manager_store.clear()
    yield
    rm._runtime_store.clear()
    rm._state_manager_store.clear()


@pytest.fixture
def client():
    """FastAPI test client."""
    return TestClient(app)


@pytest.fixture
def session_id():
    """Create a fresh session and return its ID."""
    return rm.create_session()
