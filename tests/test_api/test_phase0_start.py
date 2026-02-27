"""
Phase 0 — POST /reconciliation/start

Verifies every requirement for session initialization:

  [HTTP]
  - Returns 200 with session_id and current_state fields
  - session_id is a valid UUID4 string
  - current_state value is exactly "initialized"
  - Empty body and explicit null metadata are both accepted

  [Architecture]
  - Session is persisted in the in-memory runtime store
  - Runtime container has the correct structure and initial values
  - No snapshot is created during initialization (Phase 0 contract)
  - raw_data fields are None (no files loaded yet)
  - matching buckets are all empty (no computation run)
  - snapshots dict is empty

  [Isolation]
  - Each call creates a distinct session with an independent runtime
"""

import uuid
import pytest

import src.core.runtime_manager as rm


URL = "/reconciliation/start"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _post(client, body=None):
    """POST to /reconciliation/start; body=None sends an empty request."""
    if body is None:
        return client.post(URL)
    return client.post(URL, json=body)


def _post_ok(client, body=None):
    """Assert 200 and return the parsed JSON body."""
    resp = _post(client, body)
    assert resp.status_code == 200, resp.text
    return resp.json()


# ---------------------------------------------------------------------------
# HTTP response shape
# ---------------------------------------------------------------------------

class TestResponseShape:
    def test_status_200(self, client):
        assert _post(client).status_code == 200

    def test_response_has_session_id_key(self, client):
        data = _post_ok(client)
        assert "session_id" in data

    def test_response_has_current_state_key(self, client):
        data = _post_ok(client)
        assert "current_state" in data

    def test_response_has_no_extra_keys(self, client):
        data = _post_ok(client)
        assert set(data.keys()) == {"session_id", "current_state"}

    def test_current_state_is_initialized(self, client):
        data = _post_ok(client)
        assert data["current_state"] == "initialized"

    def test_session_id_is_valid_uuid(self, client):
        data = _post_ok(client)
        # Raises ValueError if not a valid UUID
        parsed = uuid.UUID(data["session_id"])
        assert parsed.version == 4

    def test_session_id_is_string(self, client):
        data = _post_ok(client)
        assert isinstance(data["session_id"], str)


# ---------------------------------------------------------------------------
# Request body variants
# ---------------------------------------------------------------------------

class TestRequestBody:
    def test_empty_body_accepted(self, client):
        """No body at all — uses SessionCreateRequest defaults."""
        assert _post(client).status_code == 200

    def test_explicit_null_metadata_accepted(self, client):
        assert _post(client, {"metadata": None}).status_code == 200

    def test_empty_metadata_dict_accepted(self, client):
        assert _post(client, {"metadata": {}}).status_code == 200

    def test_metadata_with_config_overrides_accepted(self, client):
        body = {"metadata": {"threshold": 0.85, "ai_model": "gpt-4o"}}
        data = _post_ok(client, body)
        assert data["current_state"] == "initialized"


# ---------------------------------------------------------------------------
# In-memory persistence
# ---------------------------------------------------------------------------

class TestRuntimePersistence:
    def test_session_stored_after_creation(self, client):
        data = _post_ok(client)
        assert rm.session_exists(data["session_id"])

    def test_current_state_matches_response(self, client):
        data = _post_ok(client)
        stored_state = rm.get_current_state(data["session_id"])
        assert stored_state.value == data["current_state"]

    def test_runtime_current_state_field_is_initialized(self, client):
        data = _post_ok(client)
        runtime = rm.get_runtime(data["session_id"])
        assert runtime["current_state"] == "initialized"

    def test_runtime_session_id_matches_response(self, client):
        data = _post_ok(client)
        runtime = rm.get_runtime(data["session_id"])
        assert runtime["session_id"] == data["session_id"]


# ---------------------------------------------------------------------------
# Runtime container structure
# ---------------------------------------------------------------------------

class TestRuntimeStructure:
    """
    Verify every top-level key of the runtime container is present
    and set to its correct initial value.
    """

    def _runtime(self, client):
        data = _post_ok(client)
        return rm.get_runtime(data["session_id"])

    def test_has_session_id(self, client):
        r = self._runtime(client)
        assert "session_id" in r

    def test_has_current_state(self, client):
        r = self._runtime(client)
        assert "current_state" in r

    def test_raw_data_keys_present(self, client):
        r = self._runtime(client)
        assert set(r["raw_data"].keys()) == {"chart_of_accounts", "gl", "subledger"}

    def test_raw_data_all_none(self, client):
        """No files loaded yet — all raw_data values must be None."""
        r = self._runtime(client)
        for key, value in r["raw_data"].items():
            assert value is None, f"raw_data['{key}'] should be None, got {type(value)}"

    def test_clean_data_is_empty_dict(self, client):
        r = self._runtime(client)
        assert r["clean_data"] == {}

    def test_vendor_normalization_map_is_empty_list(self, client):
        r = self._runtime(client)
        assert r["vendor_normalization_map"] == []

    def test_profiling_is_empty_dict(self, client):
        r = self._runtime(client)
        assert r["profiling"] == {}

    def test_matching_buckets_present(self, client):
        r = self._runtime(client)
        assert set(r["matching"].keys()) == {
            "deterministic", "probabilistic", "ai_suggested", "final", "rejected"
        }

    def test_matching_buckets_all_empty(self, client):
        """No matching has run — every bucket must be an empty list."""
        r = self._runtime(client)
        for bucket, records in r["matching"].items():
            assert records == [], f"matching['{bucket}'] should be [], got {records}"

    def test_residual_pool_is_empty(self, client):
        r = self._runtime(client)
        assert r["residual_pool"] == {}

    def test_config_present(self, client):
        r = self._runtime(client)
        assert "config" in r

    def test_config_vendor_nlp_threshold_default(self, client):
        r = self._runtime(client)
        assert r["config"]["vendor_nlp_threshold"] == 0.90


# ---------------------------------------------------------------------------
# Phase 0 contract: no snapshot created
# ---------------------------------------------------------------------------

class TestNoSnapshotOnInit:
    def test_snapshots_dict_is_empty(self, client):
        """
        Architecture rule: no snapshot is written during initialization.
        Snapshots are only created immediately before a state transition.
        Phase 0 creates the session without advancing state, so the
        snapshots container must be empty.
        """
        data = _post_ok(client)
        runtime = rm.get_runtime(data["session_id"])
        assert runtime["snapshots"] == {}

    def test_snapshot_count_is_zero_via_manager(self, client):
        data = _post_ok(client)
        snapshots = rm.get_session_snapshots(data["session_id"])
        assert len(snapshots) == 0

    def test_session_is_not_in_review_phase(self, client):
        """INITIALIZED is not a review state."""
        data = _post_ok(client)
        assert not rm.is_review_phase(data["session_id"])


# ---------------------------------------------------------------------------
# Session isolation
# ---------------------------------------------------------------------------

class TestSessionIsolation:
    def test_two_calls_produce_distinct_session_ids(self, client):
        a = _post_ok(client)
        b = _post_ok(client)
        assert a["session_id"] != b["session_id"]

    def test_sessions_do_not_share_runtime(self, client):
        """Mutating one session's runtime must not affect another."""
        a = _post_ok(client)
        b = _post_ok(client)

        runtime_a = rm.get_runtime(a["session_id"])
        runtime_b = rm.get_runtime(b["session_id"])

        # Directly mutate a's runtime (simulating controlled write)
        runtime_a["profiling"]["test_key"] = "test_value"

        assert "test_key" not in runtime_b.get("profiling", {})

    def test_all_sessions_listed(self, client):
        a = _post_ok(client)
        b = _post_ok(client)
        session_ids = rm.list_session_ids()
        assert a["session_id"] in session_ids
        assert b["session_id"] in session_ids
