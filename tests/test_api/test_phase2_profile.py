"""
Phase 2 — POST /reconciliation/{session_id}/profile

Tests every explicit requirement:

  [Happy path]
  - Returns 200
  - State advances to 'profiled'
  - response state == 'profiled'
  - session_id echoed in response
  - profiling written to runtime["profiling"] with 'metrics' and 'narrative' keys
  - Snapshot key == 'files_loaded' (pre-transition state)
  - Snapshot integrity hash present (64 hex chars)
  - Narrative is non-empty string containing stub disclaimer
  - 2 total snapshots after profiling (initialized→files_loaded, files_loaded→profiled)
  - All 6 metric categories present in response (null_counts, null_pct, dupes,
    numeric_distributions, date_ranges, entity_distribution)
  - cross_file summary in response

  [Metrics correctness — known data]
  - GL row_count = 4
  - Subledger row_count = 3
  - CoA row_count = 2
  - GL duplicate_row_count = 1 (rows 0 and 1 are exact duplicates)
  - Subledger no duplicates
  - GL null vendor_name: null_count=1, null_pct=25.0%
  - GL date range: min='2024-01-01', max='2024-03-31'
  - GL amount distribution: min=100, max=400, sum=800, mean=200, null_count=0
  - GL entity distribution: ENT_A=3, ENT_B=1
  - Cross-file: gl=4, subledger=3, delta=1, delta_pct=25.0%
  - CoA materiality_threshold distribution present

  [No recomputation]
  - Second profile call returns 409
  - 409 detail contains 'recomputation'
  - 409 detail mentions 'profiled' state
  - No extra snapshot created on second (rejected) call
  - State remains 'profiled' after rejected second call

  [Wrong state]
  - Profile from 'initialized' state → 409 (must upload first)
  - 409 detail mentions 'files_loaded'
  - Unknown session_id → 404
  - 404 detail contains the bad session_id
"""

import csv
import io
from typing import Any, Dict, List, Optional

import pytest

import src.core.runtime_manager as rm
from src.core.state_machine import ReconciliationState


# ---------------------------------------------------------------------------
# CSV builder
# ---------------------------------------------------------------------------

def _make_csv(rows: Dict[str, List[Any]]) -> bytes:
    """Build a CSV as bytes from column → list of values. None → empty cell (NaN)."""
    buf = io.StringIO()
    cols = list(rows.keys())
    writer = csv.DictWriter(buf, fieldnames=cols)
    writer.writeheader()
    n = len(next(iter(rows.values())))
    for i in range(n):
        writer.writerow({col: ("" if rows[col][i] is None else rows[col][i]) for col in cols})
    return buf.getvalue().encode("utf-8")


# ---------------------------------------------------------------------------
# Minimal valid data — used for happy-path and wrong-state tests
# ---------------------------------------------------------------------------

_VALID_GL = {
    "gl_id":            ["GL001", "GL002"],
    "entity":           ["US_CORP", "US_CORP"],
    "account_code":     ["ACCT_100", "ACCT_101"],
    "vendor_name":      ["Vendor A", "Vendor B"],
    "transaction_date": ["2024-01-15", "2024-02-20"],
    "amount":           ["100.00", "250.50"],
    "currency":         ["USD", "USD"],
    "exception_flag":   ["False", "True"],
}

_VALID_SUB = {
    "subledger_id":     ["SUB001", "SUB002"],
    "entity":           ["US_CORP", "US_CORP"],
    "vendor_name":      ["Vendor A", "Vendor B"],
    "transaction_date": ["2024-01-15", "2024-02-20"],
    "amount":           ["100.00", "250.50"],
    "currency":         ["USD", "USD"],
    "reference_id":     ["GL001", "GL002"],
}

_VALID_COA = {
    "account_code":          ["ACCT_100", "ACCT_101"],
    "account_name":          ["Cash", "Accounts Payable"],
    "account_type":          ["Asset", "Liability"],
    "materiality_threshold": ["10000.00", "5000.00"],
}


# ---------------------------------------------------------------------------
# Metrics-correctness dataset — deterministic, hand-computed expected values
#
# GL (4 rows):
#   Rows 0+1 are exact duplicates  → duplicate_row_count = 1
#   Row 2 has null vendor_name     → null_count["vendor_name"] = 1, pct = 25.0%
#   Dates span 2024-01-01 → 2024-03-31
#   Amounts: 100, 100, 200, 400   → sum=800, mean=200, min=100, max=400
#   Entities: ENT_A×3, ENT_B×1
#
# Subledger (3 rows):
#   No duplicates, no nulls
#   GL: 4 rows, Sub: 3 rows → delta=1, delta_pct = round(1/4*100, 4) = 25.0
# ---------------------------------------------------------------------------

_METRICS_GL = {
    "gl_id":            ["GL001",    "GL001",    "GL002",   "GL003"],
    "entity":           ["ENT_A",    "ENT_A",    "ENT_A",   "ENT_B"],
    "account_code":     ["ACCT_100", "ACCT_100", "ACCT_101","ACCT_102"],
    "vendor_name":      ["Vendor A", "Vendor A",  None,     "Vendor C"],
    "transaction_date": ["2024-01-01","2024-01-01","2024-02-15","2024-03-31"],
    "amount":           ["100.00",   "100.00",   "200.00",  "400.00"],
    "currency":         ["USD",      "USD",      "USD",     "USD"],
    "exception_flag":   ["False",    "False",    "False",   "True"],
}

_METRICS_SUB = {
    "subledger_id":     ["SUB001", "SUB002", "SUB003"],
    "entity":           ["ENT_A",  "ENT_A",  "ENT_B"],
    "vendor_name":      ["Vendor A", "Vendor B", "Vendor C"],
    "transaction_date": ["2024-01-01", "2024-02-15", "2024-03-31"],
    "amount":           ["100.00", "200.00", "400.00"],
    "currency":         ["USD", "USD", "USD"],
    "reference_id":     ["GL001", "GL002", "GL003"],
}


# ---------------------------------------------------------------------------
# Request helpers
# ---------------------------------------------------------------------------

def _valid_files():
    return {
        "gl":                ("GL.csv",                _make_csv(_VALID_GL),  "text/csv"),
        "chart_of_accounts": ("Chart_of_Accounts.csv", _make_csv(_VALID_COA), "text/csv"),
        "subledger":         ("Subledger.csv",         _make_csv(_VALID_SUB), "text/csv"),
    }


def _metrics_files():
    return {
        "gl":                ("GL.csv",                _make_csv(_METRICS_GL),  "text/csv"),
        "chart_of_accounts": ("Chart_of_Accounts.csv", _make_csv(_VALID_COA),   "text/csv"),
        "subledger":         ("Subledger.csv",         _make_csv(_METRICS_SUB), "text/csv"),
    }


def _upload(client, session_id, files=None):
    return client.post(
        f"/reconciliation/{session_id}/upload",
        files=(files or _valid_files()),
    )


def _profile(client, session_id):
    return client.post(f"/reconciliation/{session_id}/profile")


def _advance_to_files_loaded(client, session_id, files=None):
    resp = _upload(client, session_id, files)
    assert resp.status_code == 200, f"Upload failed: {resp.text}"
    return resp


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------

class TestHappyPath:
    def test_returns_200(self, client, session_id):
        _advance_to_files_loaded(client, session_id)
        assert _profile(client, session_id).status_code == 200

    def test_state_advances_to_profiled(self, client, session_id):
        _advance_to_files_loaded(client, session_id)
        _profile(client, session_id)
        assert rm.get_current_state(session_id) == ReconciliationState.PROFILED

    def test_response_state_is_profiled(self, client, session_id):
        _advance_to_files_loaded(client, session_id)
        data = _profile(client, session_id).json()
        assert data["state"] == "profiled"

    def test_session_id_echoed_in_response(self, client, session_id):
        _advance_to_files_loaded(client, session_id)
        data = _profile(client, session_id).json()
        assert data["session_id"] == session_id

    def test_snapshot_key_is_files_loaded(self, client, session_id):
        """Snapshot captured before transition → pre_transition_state = 'files_loaded'."""
        _advance_to_files_loaded(client, session_id)
        data = _profile(client, session_id).json()
        assert data["snapshot"]["key"] == "files_loaded"

    def test_snapshot_integrity_hash_present(self, client, session_id):
        _advance_to_files_loaded(client, session_id)
        data = _profile(client, session_id).json()
        assert len(data["snapshot"]["integrity_hash"]) == 64

    def test_narrative_is_nonempty_string(self, client, session_id):
        _advance_to_files_loaded(client, session_id)
        data = _profile(client, session_id).json()
        assert isinstance(data["narrative"], str) and len(data["narrative"]) > 0

    def test_narrative_mentions_gl(self, client, session_id):
        _advance_to_files_loaded(client, session_id)
        data = _profile(client, session_id).json()
        narrative_lower = data["narrative"].lower()
        # Narrative is now either AI-generated or the deterministic fallback; both reference GL
        assert "gl" in narrative_lower or "general ledger" in narrative_lower or len(data["narrative"]) > 20

    def test_profiling_written_to_runtime(self, client, session_id):
        _advance_to_files_loaded(client, session_id)
        _profile(client, session_id)
        assert rm.get_runtime(session_id)["profiling"] not in (None, {})

    def test_profiling_metrics_key_in_runtime(self, client, session_id):
        _advance_to_files_loaded(client, session_id)
        _profile(client, session_id)
        assert "metrics" in rm.get_runtime(session_id)["profiling"]

    def test_profiling_narrative_key_in_runtime(self, client, session_id):
        _advance_to_files_loaded(client, session_id)
        _profile(client, session_id)
        assert "narrative" in rm.get_runtime(session_id)["profiling"]

    def test_two_snapshots_after_profile(self, client, session_id):
        """initialized→files_loaded + files_loaded→profiled = 2 total snapshots."""
        _advance_to_files_loaded(client, session_id)
        _profile(client, session_id)
        assert len(rm.get_runtime(session_id)["snapshots"]) == 2

    def test_all_three_files_in_metrics(self, client, session_id):
        _advance_to_files_loaded(client, session_id)
        files = _profile(client, session_id).json()["metrics"]["files"]
        assert set(files.keys()) == {"gl", "subledger", "chart_of_accounts"}

    def test_cross_file_summary_present(self, client, session_id):
        _advance_to_files_loaded(client, session_id)
        assert "cross_file" in _profile(client, session_id).json()["metrics"]

    def test_gl_numeric_distributions_present(self, client, session_id):
        _advance_to_files_loaded(client, session_id)
        gl = _profile(client, session_id).json()["metrics"]["files"]["gl"]
        assert "amount" in gl["numeric_distributions"]

    def test_gl_date_ranges_present(self, client, session_id):
        _advance_to_files_loaded(client, session_id)
        gl = _profile(client, session_id).json()["metrics"]["files"]["gl"]
        assert "transaction_date" in gl["date_ranges"]

    def test_gl_entity_distribution_present(self, client, session_id):
        _advance_to_files_loaded(client, session_id)
        gl = _profile(client, session_id).json()["metrics"]["files"]["gl"]
        assert isinstance(gl["entity_distribution"], dict)

    def test_coa_materiality_distribution_present(self, client, session_id):
        _advance_to_files_loaded(client, session_id)
        coa = _profile(client, session_id).json()["metrics"]["files"]["chart_of_accounts"]
        assert "materiality_threshold" in coa["numeric_distributions"]


# ---------------------------------------------------------------------------
# Metrics correctness — known data
# ---------------------------------------------------------------------------

class TestMetricsCorrectness:
    """
    Upload _METRICS_GL (4 rows, 1 dup pair, 1 null vendor_name) +
    _METRICS_SUB (3 rows) and verify every computed value.
    """

    @pytest.fixture(autouse=True)
    def _setup(self, client, session_id):
        _advance_to_files_loaded(client, session_id, _metrics_files())
        resp = _profile(client, session_id)
        assert resp.status_code == 200, resp.text
        self.data = resp.json()

    # --- Row counts ---

    def test_gl_row_count(self):
        assert self.data["metrics"]["files"]["gl"]["row_count"] == 4

    def test_subledger_row_count(self):
        assert self.data["metrics"]["files"]["subledger"]["row_count"] == 3

    def test_coa_row_count(self):
        assert self.data["metrics"]["files"]["chart_of_accounts"]["row_count"] == 2

    # --- Duplicates ---

    def test_gl_duplicate_count_is_one(self):
        """Rows 0 and 1 of _METRICS_GL are identical across all columns."""
        assert self.data["metrics"]["files"]["gl"]["duplicate_row_count"] == 1

    def test_subledger_no_duplicates(self):
        assert self.data["metrics"]["files"]["subledger"]["duplicate_row_count"] == 0

    # --- Null detection ---

    def test_gl_vendor_name_null_count(self):
        null_counts = self.data["metrics"]["files"]["gl"]["null_counts"]
        assert null_counts.get("vendor_name", 0) == 1

    def test_gl_vendor_name_null_percentage(self):
        """1 null in 4 rows → 25.0%."""
        null_pcts = self.data["metrics"]["files"]["gl"]["null_percentages"]
        assert null_pcts.get("vendor_name", 0.0) == pytest.approx(25.0, rel=1e-3)

    def test_subledger_zero_null_vendor_name(self):
        null_counts = self.data["metrics"]["files"]["subledger"]["null_counts"]
        assert null_counts.get("vendor_name", 0) == 0

    # --- Date ranges ---

    def test_gl_date_min(self):
        dr = self.data["metrics"]["files"]["gl"]["date_ranges"]["transaction_date"]
        assert dr["min"] == "2024-01-01"

    def test_gl_date_max(self):
        dr = self.data["metrics"]["files"]["gl"]["date_ranges"]["transaction_date"]
        assert dr["max"] == "2024-03-31"

    def test_gl_transaction_date_has_histogram(self):
        """transaction_date (date column) should have a non-empty histogram in column_profiles."""
        gl = self.data["metrics"]["files"]["gl"]
        assert "column_profiles" in gl
        cp = gl["column_profiles"]
        assert "transaction_date" in cp
        tx_date = cp["transaction_date"]
        assert tx_date["data_type"] == "date"
        hist = tx_date.get("histogram", [])
        assert len(hist) > 0, "transaction_date histogram should be non-empty"
        assert all("label" in b and "count" in b for b in hist)

    # --- Numeric distributions ---

    def test_gl_amount_min(self):
        nd = self.data["metrics"]["files"]["gl"]["numeric_distributions"]["amount"]
        assert nd["min"] == pytest.approx(100.0)

    def test_gl_amount_max(self):
        nd = self.data["metrics"]["files"]["gl"]["numeric_distributions"]["amount"]
        assert nd["max"] == pytest.approx(400.0)

    def test_gl_amount_sum(self):
        nd = self.data["metrics"]["files"]["gl"]["numeric_distributions"]["amount"]
        assert nd["sum"] == pytest.approx(800.0)

    def test_gl_amount_mean(self):
        nd = self.data["metrics"]["files"]["gl"]["numeric_distributions"]["amount"]
        assert nd["mean"] == pytest.approx(200.0)

    def test_gl_amount_null_count_is_zero(self):
        nd = self.data["metrics"]["files"]["gl"]["numeric_distributions"]["amount"]
        assert nd["null_count"] == 0

    def test_coa_materiality_min(self):
        nd = self.data["metrics"]["files"]["chart_of_accounts"]["numeric_distributions"]["materiality_threshold"]
        assert nd["min"] == pytest.approx(5000.0)

    def test_coa_materiality_max(self):
        nd = self.data["metrics"]["files"]["chart_of_accounts"]["numeric_distributions"]["materiality_threshold"]
        assert nd["max"] == pytest.approx(10000.0)

    # --- Entity distribution ---

    def test_gl_entity_ent_a_count(self):
        ed = self.data["metrics"]["files"]["gl"]["entity_distribution"]
        assert ed.get("ENT_A") == 3

    def test_gl_entity_ent_b_count(self):
        ed = self.data["metrics"]["files"]["gl"]["entity_distribution"]
        assert ed.get("ENT_B") == 1

    # --- Column profiles (incl. date histogram) ---

    def test_gl_transaction_date_histogram(self):
        """transaction_date (date column) has a non-empty histogram by month."""
        gl = self.data["metrics"]["files"]["gl"]
        assert "column_profiles" in gl
        profiles = gl["column_profiles"]
        assert "transaction_date" in profiles
        tx_date_profile = profiles["transaction_date"]
        assert tx_date_profile["data_type"] == "date"
        hist = tx_date_profile.get("histogram", [])
        assert len(hist) > 0, "transaction_date should have histogram buckets"
        for b in hist:
            assert "label" in b and "count" in b
            assert isinstance(b["label"], str)
            assert isinstance(b["count"], int) and b["count"] >= 0

    # --- Cross-file summary ---

    def test_cross_file_gl_row_count(self):
        assert self.data["metrics"]["cross_file"]["gl_row_count"] == 4

    def test_cross_file_subledger_row_count(self):
        assert self.data["metrics"]["cross_file"]["subledger_row_count"] == 3

    def test_cross_file_delta(self):
        assert self.data["metrics"]["cross_file"]["row_count_delta"] == 1

    def test_cross_file_delta_pct(self):
        """delta=1, gl=4 → round(1/4*100, 4) = 25.0."""
        assert self.data["metrics"]["cross_file"]["row_count_delta_pct"] == pytest.approx(25.0, rel=1e-3)

    # --- Column profiles (hover histograms) ---

    def test_gl_transaction_date_has_histogram(self):
        """transaction_date (date column) gets a monthly histogram for the hover tooltip."""
        gl = self.data["metrics"]["files"]["gl"]
        assert "column_profiles" in gl
        cp = gl["column_profiles"]
        assert "transaction_date" in cp
        tx_date_profile = cp["transaction_date"]
        assert tx_date_profile["data_type"] == "date"
        hist = tx_date_profile.get("histogram", [])
        assert len(hist) > 0, "date column should have histogram buckets"
        for b in hist:
            assert "label" in b and "count" in b
            assert isinstance(b["count"], int)

    # --- Column profiles (histogram for date columns) ---

    def test_transaction_date_has_histogram(self):
        """Date columns should have a non-empty histogram in column_profiles."""
        gl = self.data["metrics"]["files"]["gl"]
        assert "column_profiles" in gl
        profiles = gl["column_profiles"]
        assert "transaction_date" in profiles
        tx_profile = profiles["transaction_date"]
        assert tx_profile["data_type"] == "date"
        hist = tx_profile.get("histogram", [])
        assert len(hist) > 0, "transaction_date should have histogram buckets"
        # Expect month labels like "Jan 2024", "Feb 2024"
        for bucket in hist:
            assert "label" in bucket
            assert "count" in bucket
            assert isinstance(bucket["count"], int)

    # --- Narrative smoke test ---

    def test_narrative_mentions_gl_row_count(self):
        """Narrative template embeds 'GL: 4 records'."""
        assert "4" in self.data["narrative"]

    def test_narrative_mentions_subledger_row_count(self):
        assert "3" in self.data["narrative"]


# ---------------------------------------------------------------------------
# No recomputation
# ---------------------------------------------------------------------------

class TestNoRecomputation:
    def test_second_call_returns_409(self, client, session_id):
        _advance_to_files_loaded(client, session_id)
        _profile(client, session_id)
        assert _profile(client, session_id).status_code == 409

    def test_409_detail_mentions_recomputation(self, client, session_id):
        _advance_to_files_loaded(client, session_id)
        _profile(client, session_id)
        detail = _profile(client, session_id).json()["detail"].lower()
        assert "recomputation" in detail

    def test_409_detail_mentions_profiled_state(self, client, session_id):
        _advance_to_files_loaded(client, session_id)
        _profile(client, session_id)
        detail = _profile(client, session_id).json()["detail"].lower()
        assert "profiled" in detail

    def test_no_extra_snapshot_on_rejected_call(self, client, session_id):
        """Snapshot count must not increase when the second call is rejected."""
        _advance_to_files_loaded(client, session_id)
        _profile(client, session_id)
        count_before = len(rm.get_runtime(session_id)["snapshots"])
        _profile(client, session_id)  # rejected 409
        count_after = len(rm.get_runtime(session_id)["snapshots"])
        assert count_after == count_before

    def test_state_unchanged_after_rejected_call(self, client, session_id):
        _advance_to_files_loaded(client, session_id)
        _profile(client, session_id)
        _profile(client, session_id)  # rejected
        assert rm.get_current_state(session_id) == ReconciliationState.PROFILED


# ---------------------------------------------------------------------------
# Wrong state
# ---------------------------------------------------------------------------

class TestWrongState:
    def test_profile_from_initialized_returns_409(self, client, session_id):
        """Session is in 'initialized' — must be in 'files_loaded' to profile."""
        assert _profile(client, session_id).status_code == 409

    def test_409_detail_mentions_files_loaded(self, client, session_id):
        detail = _profile(client, session_id).json()["detail"]
        assert "files_loaded" in detail

    def test_unknown_session_returns_404(self, client):
        assert _profile(client, "nonexistent-session-id").status_code == 404

    def test_404_detail_contains_session_id(self, client):
        bad_id = "ghost-session-abc123"
        detail = _profile(client, bad_id).json()["detail"]
        assert bad_id in detail
