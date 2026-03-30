"""
Phase 4 — POST /reconciliation/{session_id}/deterministic

Tests every explicit requirement:

  [Happy path]
  - Returns 200
  - State advances to 'deterministic_complete'
  - response state == 'deterministic_complete'
  - session_id echoed in response
  - matches list present in response
  - summary present in response
  - Snapshot key == 'matching_configured' (pre-transition state)
  - Snapshot integrity hash present (64 hex chars)
  - 6 total snapshots after deterministic
    (initialized→files_loaded, files_loaded→column_mapping_complete,
     column_mapping_complete→profiled, profiled→preprocessed,
     preprocessed→matching_configured, matching_configured→deterministic_complete)
  - matches written to runtime["matching"]["deterministic"]
  - residual_pool written to runtime["residual_pool"]
  - residual_pool has "gl" and "subledger" keys

  [Known result — standard test data]
  GL:  "Vendor A LLC" ($100.00, 2024-01-15, US_CORP) → scenario 1 match w/ SUB001
       "Vendor B"     ($250.50, 2024-01-15, US_CORP) → scenario 3 match w/ SUB002
  Sub: "Vendor A"    ($100.00, 2024-01-15, US_CORP)
       "Vendor B"    ($250.50, 2024-02-20, US_CORP)
  After preprocessing, Vendor_Normalized values allow:
    scenario 1: GL001 ↔ SUB001 (exact vendor/amount/date/entity)
    scenario 3: GL002 ↔ SUB002 (vendor+amount+entity match, 36-day gap ≤ 60)
  Expected: 2 matches, 0 residual GL, 0 residual Sub

  - GL001 matched in scenario 1
  - GL002 matched in scenario 3
  - Match count is 2
  - scenario_counts[1] == 1, scenario_counts[3] == 1
  - Residual GL is empty
  - Residual Sub is empty
  - summary.total_gl_records == 2
  - summary.total_sub_records == 2
  - summary.matched_gl_records == 2
  - summary.matched_sub_records == 2

  [No recomputation]
  - Second deterministic call returns 409
  - 409 detail contains 'recomputation'
  - 409 detail mentions 'deterministic_complete'
  - No extra snapshot created on rejected call
  - State remains 'deterministic_complete' after rejected call

  [Wrong state]
  - Deterministic from 'initialized' → 409 with 'matching_configured' mention
  - Deterministic from 'files_loaded' → 409 with 'matching_configured' mention
  - Deterministic from 'profiled'     → 409 with 'matching_configured' mention
  - Unknown session → 404 with session_id in detail
"""

import csv
import io
from typing import Any, Dict, List

import pytest

import src.core.runtime_manager as rm
from src.core.state_machine import ReconciliationState


# ---------------------------------------------------------------------------
# CSV builder (shared pattern)
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
# Standard test data
#
# After Phase 3 vendor normalisation:
#   GL "Vendor A LLC" → Vendor_Normalized = "vendor a"   (tier-1 match)
#   GL "Vendor B"     → Vendor_Normalized = "vendor b"
#   Sub "Vendor A"    → Vendor_Normalized = "vendor a"
#   Sub "Vendor B"    → Vendor_Normalized = "vendor b"
#
# Deterministic matching:
#   Scenario 1: GL001 (vendor a, 100.00, 2024-01-15, US_CORP) ↔ SUB001 (exact)
#   Scenario 3: GL002 (vendor b, 250.50, 2024-01-15, US_CORP) ↔ SUB002 (36-day gap ≤ 60)
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


def _advance_to_preprocessed(client, session_id):
    """Upload + profile + preprocess to reach the 'preprocessed' pre-condition."""
    r1 = _upload(client, session_id)
    assert r1.status_code == 200, f"Upload failed: {r1.text}"
    rm.advance_state(session_id, ReconciliationState.COLUMN_MAPPING_COMPLETE)
    r2 = _profile(client, session_id)
    assert r2.status_code == 200, f"Profile failed: {r2.text}"
    r3 = _preprocess(client, session_id)
    assert r3.status_code == 200, f"Preprocess failed: {r3.text}"
    rm.advance_state(session_id, ReconciliationState.MATCHING_CONFIGURED)


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------

class TestHappyPath:
    def test_returns_200(self, client, session_id):
        _advance_to_preprocessed(client, session_id)
        assert _deterministic(client, session_id).status_code == 200

    def test_state_advances_to_deterministic_complete(self, client, session_id):
        _advance_to_preprocessed(client, session_id)
        _deterministic(client, session_id)
        assert rm.get_current_state(session_id) == ReconciliationState.DETERMINISTIC_COMPLETE

    def test_response_state_is_deterministic_complete(self, client, session_id):
        _advance_to_preprocessed(client, session_id)
        data = _deterministic(client, session_id).json()
        assert data["state"] == "deterministic_complete"

    def test_session_id_echoed(self, client, session_id):
        _advance_to_preprocessed(client, session_id)
        data = _deterministic(client, session_id).json()
        assert data["session_id"] == session_id

    def test_matches_present(self, client, session_id):
        _advance_to_preprocessed(client, session_id)
        data = _deterministic(client, session_id).json()
        assert "matches" in data
        assert isinstance(data["matches"], list)

    def test_summary_present(self, client, session_id):
        _advance_to_preprocessed(client, session_id)
        data = _deterministic(client, session_id).json()
        assert "summary" in data

    def test_snapshot_key_is_preprocessed(self, client, session_id):
        """Snapshot captured before transition → pre_transition_state = 'matching_configured'."""
        _advance_to_preprocessed(client, session_id)
        data = _deterministic(client, session_id).json()
        assert data["snapshot"]["key"] == "matching_configured"

    def test_snapshot_integrity_hash_present(self, client, session_id):
        _advance_to_preprocessed(client, session_id)
        data = _deterministic(client, session_id).json()
        assert len(data["snapshot"]["integrity_hash"]) == 64

    def test_four_snapshots_after_deterministic(self, client, session_id):
        """initialized→files_loaded, files_loaded→column_mapping_complete,
        column_mapping_complete→profiled, profiled→preprocessed,
        preprocessed→matching_configured, matching_configured→deterministic_complete."""
        _advance_to_preprocessed(client, session_id)
        _deterministic(client, session_id)
        assert len(rm.get_runtime(session_id)["snapshots"]) == 6

    def test_matches_written_to_runtime(self, client, session_id):
        _advance_to_preprocessed(client, session_id)
        _deterministic(client, session_id)
        runtime = rm.get_runtime(session_id)
        assert isinstance(runtime["matching"]["deterministic"], list)

    def test_residual_pool_written_to_runtime(self, client, session_id):
        _advance_to_preprocessed(client, session_id)
        _deterministic(client, session_id)
        runtime = rm.get_runtime(session_id)
        assert isinstance(runtime["residual_pool"], dict)

    def test_residual_pool_has_gl_key(self, client, session_id):
        _advance_to_preprocessed(client, session_id)
        _deterministic(client, session_id)
        assert "gl" in rm.get_runtime(session_id)["residual_pool"]

    def test_residual_pool_has_subledger_key(self, client, session_id):
        _advance_to_preprocessed(client, session_id)
        _deterministic(client, session_id)
        assert "subledger" in rm.get_runtime(session_id)["residual_pool"]


# ---------------------------------------------------------------------------
# Known result — standard test data
# ---------------------------------------------------------------------------

class TestKnownResult:
    """
    Standard test data always produces:
      - 2 matches (1 in scenario 1, 1 in scenario 3)
      - 0 residual GL, 0 residual Sub
    """

    @pytest.fixture(autouse=True)
    def _setup(self, client, session_id):
        _advance_to_preprocessed(client, session_id)
        resp = _deterministic(client, session_id)
        assert resp.status_code == 200, resp.text
        self.data = resp.json()
        self.session_id = session_id

    def test_match_count_is_two(self):
        assert len(self.data["matches"]) == 2

    def test_summary_match_count_is_two(self):
        assert self.data["summary"]["match_count"] == 2

    def test_gl001_matched_in_scenario_1(self):
        s1_matches = [m for m in self.data["matches"] if m["scenario_id"] == 1]
        gl_ids = [rid for m in s1_matches for rid in m["record_ids_A"]]
        assert "GL001" in gl_ids

    def test_sub001_matched_in_scenario_1(self):
        s1_matches = [m for m in self.data["matches"] if m["scenario_id"] == 1]
        sub_ids = [rid for m in s1_matches for rid in m["record_ids_B"]]
        assert "SUB001" in sub_ids

    def test_gl002_matched_in_scenario_3(self):
        s3_matches = [m for m in self.data["matches"] if m["scenario_id"] == 3]
        gl_ids = [rid for m in s3_matches for rid in m["record_ids_A"]]
        assert "GL002" in gl_ids

    def test_sub002_matched_in_scenario_3(self):
        s3_matches = [m for m in self.data["matches"] if m["scenario_id"] == 3]
        sub_ids = [rid for m in s3_matches for rid in m["record_ids_B"]]
        assert "SUB002" in sub_ids

    def test_scenario_counts_scenario_1_is_1(self):
        assert self.data["summary"]["scenario_counts"]["1"] == 1

    def test_scenario_counts_scenario_3_is_1(self):
        assert self.data["summary"]["scenario_counts"]["3"] == 1

    def test_total_gl_records_is_2(self):
        assert self.data["summary"]["total_gl_records"] == 2

    def test_total_sub_records_is_2(self):
        assert self.data["summary"]["total_sub_records"] == 2

    def test_matched_gl_records_is_2(self):
        assert self.data["summary"]["matched_gl_records"] == 2

    def test_matched_sub_records_is_2(self):
        assert self.data["summary"]["matched_sub_records"] == 2

    def test_unmatched_gl_records_is_0(self):
        assert self.data["summary"]["unmatched_gl_records"] == 0

    def test_unmatched_sub_records_is_0(self):
        assert self.data["summary"]["unmatched_sub_records"] == 0

    def test_residual_gl_is_empty(self):
        pool = rm.get_runtime(self.session_id)["residual_pool"]
        assert len(pool["gl"]) == 0

    def test_residual_sub_is_empty(self):
        pool = rm.get_runtime(self.session_id)["residual_pool"]
        assert len(pool["subledger"]) == 0

    def test_match_has_required_fields(self):
        m = self.data["matches"][0]
        for key in (
            "match_id", "record_ids_A", "record_ids_B",
            "scenario_id", "scenario_description",
            "confidence_score", "grouping_type",
            "user_status", "override_flag",
        ):
            assert key in m

    def test_match_user_status_is_auto_confirmed(self):
        for m in self.data["matches"]:
            assert m["user_status"] == "auto_confirmed"

    def test_match_override_flag_is_false(self):
        for m in self.data["matches"]:
            assert m["override_flag"] is False

    def test_deterministic_list_in_runtime_has_two_entries(self):
        det = rm.get_runtime(self.session_id)["matching"]["deterministic"]
        assert len(det) == 2


# ---------------------------------------------------------------------------
# No recomputation
# ---------------------------------------------------------------------------

class TestNoRecomputation:
    def test_second_call_returns_409(self, client, session_id):
        _advance_to_preprocessed(client, session_id)
        _deterministic(client, session_id)
        assert _deterministic(client, session_id).status_code == 409

    def test_409_detail_mentions_recomputation(self, client, session_id):
        _advance_to_preprocessed(client, session_id)
        _deterministic(client, session_id)
        detail = _deterministic(client, session_id).json()["detail"].lower()
        assert "recomputation" in detail

    def test_409_detail_mentions_deterministic_complete(self, client, session_id):
        _advance_to_preprocessed(client, session_id)
        _deterministic(client, session_id)
        detail = _deterministic(client, session_id).json()["detail"].lower()
        assert "deterministic_complete" in detail

    def test_no_extra_snapshot_on_rejected_call(self, client, session_id):
        _advance_to_preprocessed(client, session_id)
        _deterministic(client, session_id)
        count_before = len(rm.get_runtime(session_id)["snapshots"])
        _deterministic(client, session_id)  # rejected
        assert len(rm.get_runtime(session_id)["snapshots"]) == count_before

    def test_state_unchanged_after_rejected_call(self, client, session_id):
        _advance_to_preprocessed(client, session_id)
        _deterministic(client, session_id)
        _deterministic(client, session_id)  # rejected
        assert rm.get_current_state(session_id) == ReconciliationState.DETERMINISTIC_COMPLETE


# ---------------------------------------------------------------------------
# Wrong state
# ---------------------------------------------------------------------------

class TestWrongState:
    def test_deterministic_from_initialized_returns_409(self, client, session_id):
        assert _deterministic(client, session_id).status_code == 409

    def test_deterministic_from_files_loaded_returns_409(self, client, session_id):
        _upload(client, session_id)
        assert _deterministic(client, session_id).status_code == 409

    def test_deterministic_from_profiled_returns_409(self, client, session_id):
        _upload(client, session_id)
        _profile(client, session_id)
        assert _deterministic(client, session_id).status_code == 409

    def test_409_detail_mentions_preprocessed(self, client, session_id):
        detail = _deterministic(client, session_id).json()["detail"]
        assert "matching_configured" in detail

    def test_unknown_session_returns_404(self, client):
        assert _deterministic(client, "nonexistent-id").status_code == 404

    def test_404_detail_contains_session_id(self, client):
        bad_id = "ghost-session-xyz"
        assert bad_id in _deterministic(client, bad_id).json()["detail"]
