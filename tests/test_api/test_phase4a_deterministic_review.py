"""
Phase 4A — POST /reconciliation/{session_id}/deterministic/review

Tests every explicit requirement:

  [Happy path]
  - Returns 200
  - State advances to 'deterministic_review_complete'
  - response state == 'deterministic_review_complete'
  - session_id echoed in response
  - deterministic_match_count present in response
  - residual_gl_count present in response
  - residual_sub_count present in response
  - Snapshot key == 'deterministic_complete' (pre-transition state)
  - Snapshot integrity hash present (64 hex chars)
  - 7 total snapshots after review
    (initialized→files_loaded, files_loaded→column_mapping_complete,
     column_mapping_complete→profiled, profiled→preprocessed,
     preprocessed→matching_configured, matching_configured→deterministic_complete,
     deterministic_complete→deterministic_review_complete)

  [Known result — standard test data]
  After full pipeline (upload → profile → preprocess → deterministic):
    GL001 matched to SUB001 in scenario 1
    GL002 matched to SUB002 in scenario 3
  Expected: deterministic_match_count == 2, residual == 0 on both sides

  - deterministic_match_count == 2
  - residual_gl_count == 0
  - residual_sub_count == 0

  [No recomputation / no re-confirmation]
  - Second review call returns 409
  - 409 detail contains 'already confirmed'
  - 409 detail mentions 'deterministic_review_complete'
  - No extra snapshot created on rejected call
  - State remains 'deterministic_review_complete' after rejected call

  [No dataset mutation]
  - Deterministic match list unchanged after review
  - Residual pool unchanged after review

  [Wrong state]
  - Review from 'initialized'   → 409 with 'deterministic_complete' mention
  - Review from 'files_loaded'  → 409 with 'deterministic_complete' mention
  - Review from 'profiled'      → 409 with 'deterministic_complete' mention
  - Review from 'preprocessed'  → 409 with 'deterministic_complete' mention
  - Unknown session             → 404 with session_id in detail
"""

import csv
import io
from typing import Any, Dict, List

import pytest

import src.core.runtime_manager as rm
from src.core.state_machine import ReconciliationState


# ---------------------------------------------------------------------------
# CSV builder
# ---------------------------------------------------------------------------

def _make_csv(rows: Dict[str, List[Any]]) -> bytes:
    buf = io.StringIO()
    cols = list(rows.keys())
    writer = csv.DictWriter(buf, fieldnames=cols)
    writer.writeheader()
    n = len(next(iter(rows.values())))
    for i in range(n):
        writer.writerow({col: ("" if rows[col][i] is None else rows[col][i]) for col in cols})
    return buf.getvalue().encode("utf-8")


# ---------------------------------------------------------------------------
# Standard test data (identical to Phase 3 / Phase 4 test files)
# ---------------------------------------------------------------------------

_GL = {
    "gl_id":            ["GL001", "GL002"],
    "entity":           ["US_CORP", "US_CORP"],
    "account_code":     ["ACCT_100", "ACCT_101"],
    "vendor_name":      ["Vendor A LLC", "Vendor B"],
    "transaction_date": ["2024-01-15", "2024-01-15"],
    "amount":           ["100.00", "250.50"],
    "currency":         ["USD", "USD"],
    "exception_flag":   ["False", "True"],
}

_SUB = {
    "subledger_id":     ["SUB001", "SUB002"],
    "entity":           ["US_CORP", "US_CORP"],
    "vendor_name":      ["Vendor A", "Vendor B"],
    "transaction_date": ["2024-01-15", "2024-02-20"],
    "amount":           ["100.00", "250.50"],
    "currency":         ["USD", "USD"],
    "reference_id":     ["GL001", "GL002"],
}

_COA = {
    "account_code":          ["ACCT_100", "ACCT_101"],
    "account_name":          ["Cash", "Accounts Payable"],
    "account_type":          ["Asset", "Liability"],
    "materiality_threshold": ["10000.00", "5000.00"],
}


def _valid_files():
    return {
        "gl":                ("GL.csv",                _make_csv(_GL),  "text/csv"),
        "chart_of_accounts": ("Chart_of_Accounts.csv", _make_csv(_COA), "text/csv"),
        "subledger":         ("Subledger.csv",         _make_csv(_SUB), "text/csv"),
    }


# ---------------------------------------------------------------------------
# Request helpers
# ---------------------------------------------------------------------------

def _upload(client, session_id):
    return client.post(f"/reconciliation/{session_id}/upload", files=_valid_files())


def _profile(client, session_id):
    return client.post(f"/reconciliation/{session_id}/profile")


def _preprocess(client, session_id):
    return client.post(f"/reconciliation/{session_id}/preprocess")


def _deterministic(client, session_id):
    return client.post(f"/reconciliation/{session_id}/deterministic")


def _review(client, session_id):
    return client.post(f"/reconciliation/{session_id}/deterministic/review")


def _advance_to_deterministic_complete(client, session_id):
    """Upload → profile → preprocess → deterministic to reach pre-condition."""
    r1 = _upload(client, session_id)
    assert r1.status_code == 200, f"Upload failed: {r1.text}"
    rm.advance_state(session_id, ReconciliationState.COLUMN_MAPPING_COMPLETE)
    r2 = _profile(client, session_id)
    assert r2.status_code == 200, f"Profile failed: {r2.text}"
    r3 = _preprocess(client, session_id)
    assert r3.status_code == 200, f"Preprocess failed: {r3.text}"
    rm.advance_state(session_id, ReconciliationState.MATCHING_CONFIGURED)
    r4 = _deterministic(client, session_id)
    assert r4.status_code == 200, f"Deterministic failed: {r4.text}"


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------

class TestHappyPath:
    def test_returns_200(self, client, session_id):
        _advance_to_deterministic_complete(client, session_id)
        assert _review(client, session_id).status_code == 200

    def test_state_advances_to_deterministic_review_complete(self, client, session_id):
        _advance_to_deterministic_complete(client, session_id)
        _review(client, session_id)
        assert rm.get_current_state(session_id) == ReconciliationState.DETERMINISTIC_REVIEW_COMPLETE

    def test_response_state_is_deterministic_review_complete(self, client, session_id):
        _advance_to_deterministic_complete(client, session_id)
        data = _review(client, session_id).json()
        assert data["state"] == "deterministic_review_complete"

    def test_session_id_echoed(self, client, session_id):
        _advance_to_deterministic_complete(client, session_id)
        data = _review(client, session_id).json()
        assert data["session_id"] == session_id

    def test_deterministic_match_count_present(self, client, session_id):
        _advance_to_deterministic_complete(client, session_id)
        data = _review(client, session_id).json()
        assert "deterministic_match_count" in data

    def test_residual_gl_count_present(self, client, session_id):
        _advance_to_deterministic_complete(client, session_id)
        data = _review(client, session_id).json()
        assert "residual_gl_count" in data

    def test_residual_sub_count_present(self, client, session_id):
        _advance_to_deterministic_complete(client, session_id)
        data = _review(client, session_id).json()
        assert "residual_sub_count" in data

    def test_snapshot_key_is_deterministic_complete(self, client, session_id):
        """Snapshot captured before transition → pre_transition_state = 'deterministic_complete'."""
        _advance_to_deterministic_complete(client, session_id)
        data = _review(client, session_id).json()
        assert data["snapshot"]["key"] == "deterministic_complete"

    def test_snapshot_integrity_hash_present(self, client, session_id):
        _advance_to_deterministic_complete(client, session_id)
        data = _review(client, session_id).json()
        assert len(data["snapshot"]["integrity_hash"]) == 64

    def test_five_snapshots_after_review(self, client, session_id):
        """
        initialized→files_loaded, files_loaded→column_mapping_complete,
        column_mapping_complete→profiled, profiled→preprocessed,
        preprocessed→matching_configured, matching_configured→deterministic_complete,
        deterministic_complete→deterministic_review_complete.
        """
        _advance_to_deterministic_complete(client, session_id)
        _review(client, session_id)
        assert len(rm.get_runtime(session_id)["snapshots"]) == 7


# ---------------------------------------------------------------------------
# Known result — standard test data
# ---------------------------------------------------------------------------

class TestKnownResult:
    """
    Standard test data always yields 2 deterministic matches and 0 residual records.
    """

    @pytest.fixture(autouse=True)
    def _setup(self, client, session_id):
        _advance_to_deterministic_complete(client, session_id)
        resp = _review(client, session_id)
        assert resp.status_code == 200, resp.text
        self.data = resp.json()
        self.session_id = session_id

    def test_deterministic_match_count_is_2(self):
        assert self.data["deterministic_match_count"] == 2

    def test_residual_gl_count_is_0(self):
        assert self.data["residual_gl_count"] == 0

    def test_residual_sub_count_is_0(self):
        assert self.data["residual_sub_count"] == 0


# ---------------------------------------------------------------------------
# No recomputation / no re-confirmation
# ---------------------------------------------------------------------------

class TestNoReconfirmation:
    def test_second_call_returns_409(self, client, session_id):
        _advance_to_deterministic_complete(client, session_id)
        _review(client, session_id)
        assert _review(client, session_id).status_code == 409

    def test_409_detail_mentions_already_confirmed(self, client, session_id):
        _advance_to_deterministic_complete(client, session_id)
        _review(client, session_id)
        detail = _review(client, session_id).json()["detail"].lower()
        assert "already" in detail and "confirmed" in detail

    def test_409_detail_mentions_deterministic_review_complete(self, client, session_id):
        _advance_to_deterministic_complete(client, session_id)
        _review(client, session_id)
        detail = _review(client, session_id).json()["detail"].lower()
        assert "deterministic_review_complete" in detail

    def test_no_extra_snapshot_on_rejected_call(self, client, session_id):
        _advance_to_deterministic_complete(client, session_id)
        _review(client, session_id)
        count_before = len(rm.get_runtime(session_id)["snapshots"])
        _review(client, session_id)    # rejected
        assert len(rm.get_runtime(session_id)["snapshots"]) == count_before

    def test_state_unchanged_after_rejected_call(self, client, session_id):
        _advance_to_deterministic_complete(client, session_id)
        _review(client, session_id)
        _review(client, session_id)    # rejected
        assert rm.get_current_state(session_id) == ReconciliationState.DETERMINISTIC_REVIEW_COMPLETE


# ---------------------------------------------------------------------------
# No dataset mutation
# ---------------------------------------------------------------------------

class TestNoDatasetMutation:
    def test_deterministic_match_list_unchanged_after_review(self, client, session_id):
        """Match list in runtime must be identical before and after review."""
        _advance_to_deterministic_complete(client, session_id)
        before = list(rm.get_runtime(session_id)["matching"]["deterministic"])
        _review(client, session_id)
        after = rm.get_runtime(session_id)["matching"]["deterministic"]
        assert before == after

    def test_residual_pool_gl_unchanged_after_review(self, client, session_id):
        _advance_to_deterministic_complete(client, session_id)
        before_len = len(rm.get_runtime(session_id)["residual_pool"]["gl"])
        _review(client, session_id)
        assert len(rm.get_runtime(session_id)["residual_pool"]["gl"]) == before_len

    def test_residual_pool_sub_unchanged_after_review(self, client, session_id):
        _advance_to_deterministic_complete(client, session_id)
        before_len = len(rm.get_runtime(session_id)["residual_pool"]["subledger"])
        _review(client, session_id)
        assert len(rm.get_runtime(session_id)["residual_pool"]["subledger"]) == before_len


# ---------------------------------------------------------------------------
# Wrong state
# ---------------------------------------------------------------------------

class TestWrongState:
    def test_review_from_initialized_returns_409(self, client, session_id):
        assert _review(client, session_id).status_code == 409

    def test_review_from_files_loaded_returns_409(self, client, session_id):
        _upload(client, session_id)
        assert _review(client, session_id).status_code == 409

    def test_review_from_profiled_returns_409(self, client, session_id):
        _upload(client, session_id)
        _profile(client, session_id)
        assert _review(client, session_id).status_code == 409

    def test_review_from_preprocessed_returns_409(self, client, session_id):
        _upload(client, session_id)
        _profile(client, session_id)
        _preprocess(client, session_id)
        assert _review(client, session_id).status_code == 409

    def test_409_detail_mentions_deterministic_complete(self, client, session_id):
        detail = _review(client, session_id).json()["detail"]
        assert "deterministic_complete" in detail

    def test_unknown_session_returns_404(self, client):
        assert _review(client, "nonexistent-id").status_code == 404

    def test_404_detail_contains_session_id(self, client):
        bad_id = "ghost-session-xyz"
        assert bad_id in _review(client, bad_id).json()["detail"]
