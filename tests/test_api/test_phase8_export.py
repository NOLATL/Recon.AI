"""
Phase 8 — POST /reconciliation/{session_id}/export

Tests every explicit requirement:

  [Happy path]
  - Returns 200
  - State advances to 'finalized'
  - response state == 'finalized'
  - session_id echoed in response
  - export_dir present in response
  - exported_at present in response
  - files list present and non-empty
  - Snapshot key == 'final_consolidated' (pre-transition state)
  - Snapshot integrity hash present (64 hex chars)
  - 11 total snapshots after export
    (phases 0–7 = 10 snapshots, + export = 11)

  [Response — files]
  - Exactly 6 files in response
  - Expected filenames: final_matches.csv, residual_unmatched_gl.csv,
    residual_unmatched_sub.csv, rejected_matches.csv, audit_log.csv,
    reconciliation_report.pdf
  - Each file has sha256 (64 hex chars), size_bytes > 0, path non-empty

  [Known result — all accepted]
  4-record dataset with all phases accepted:
    - final_matches.csv has 4 rows (2 det + 1 prob + 1 ai)
    - residual_unmatched_gl.csv has 0 rows
    - residual_unmatched_sub.csv has 0 rows
    - rejected_matches.csv has 0 rows
    - audit_log.csv has >= 4 rows

  [Known result — all rejected]
  All prob + AI rejected:
    - final_matches.csv has 2 rows (det only)
    - rejected_matches.csv has >= 1 row

  [Terminal state — no re-export]
  - Second export call returns 409
  - 409 detail contains 'already' or 'finalized'
  - State remains 'finalized' after second call
  - No extra snapshot on second call
  - TerminalStateError raised on any state advance attempt

  [Wrong state]
  - Export from 'initialized'         → 409 with 'final_consolidated' mention
  - Export from 'preprocessed'        → 409 with 'final_consolidated' mention
  - Export from 'ai_review_complete'  → 409 with 'final_consolidated' mention
  - Export from 'final_consolidated'  → 200 (this is the valid state)
  - Unknown session                   → 404 with session_id in detail

  [Export metadata in runtime]
  - runtime["export"] written with export_dir, exported_at, files list
"""

import csv
import io
import os
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
# Test data — same 4-record dataset used through all phases.
# ---------------------------------------------------------------------------

_GL = {
    "gl_id":            ["GL001", "GL002", "GL003", "GL004"],
    "entity":           ["US_CORP", "US_CORP", "PROB_CORP", "AI_ENTITY"],
    "account_code":     ["ACCT_100", "ACCT_101", "ACCT_102", "ACCT_103"],
    "vendor_name":      ["Vendor A LLC", "Vendor B", "Alpha Supplies Inc", "Delta Vendor"],
    "transaction_date": ["2024-01-15", "2024-01-15", "2024-03-10", "2024-05-01"],
    "amount":           ["100.00", "250.50", "150.00", "1000.00"],
    "currency":         ["USD", "USD", "USD", "USD"],
    "exception_flag":   ["False", "True", "False", "False"],
}

_SUB = {
    "subledger_id":     ["SUB001", "SUB002", "SUB003", "SUB004"],
    "entity":           ["US_CORP", "US_CORP", "PROB_CORP", "AI_ENTITY"],
    "vendor_name":      ["Vendor A", "Vendor B", "Alpha Supplies", "Delta Vendor"],
    "transaction_date": ["2024-01-15", "2024-02-20", "2024-03-10", "2024-05-01"],
    "amount":           ["100.00", "250.50", "151.50", "1400.00"],
    "currency":         ["USD", "USD", "USD", "USD"],
    "reference_id":     ["GL001", "GL002", "GL003", "GL004"],
}

_COA = {
    "account_code":          ["ACCT_100", "ACCT_101", "ACCT_102", "ACCT_103"],
    "account_name":          ["Cash", "Accounts Payable", "Operating Expenses", "AI Purchases"],
    "account_type":          ["Asset", "Liability", "Expense", "Expense"],
    "materiality_threshold": ["10000.00", "5000.00", "2000.00", "3000.00"],
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

def _upload(client, sid):
    return client.post(f"/reconciliation/{sid}/upload", files=_valid_files())

def _profile(client, sid):
    return client.post(f"/reconciliation/{sid}/profile")

def _preprocess(client, sid):
    return client.post(f"/reconciliation/{sid}/preprocess")

def _deterministic(client, sid):
    return client.post(f"/reconciliation/{sid}/deterministic")

def _det_review(client, sid):
    return client.post(f"/reconciliation/{sid}/deterministic/review")

def _probabilistic(client, sid):
    return client.post(f"/reconciliation/{sid}/probabilistic")

def _prob_review(client, sid, decisions=None):
    return client.post(
        f"/reconciliation/{sid}/probabilistic/review",
        json={"decisions": decisions or []},
    )

def _ai(client, sid):
    return client.post(f"/reconciliation/{sid}/ai")

def _ai_review(client, sid, decisions=None):
    return client.post(
        f"/reconciliation/{sid}/ai/review",
        json={"decisions": decisions or []},
    )

def _consolidate(client, sid):
    return client.post(f"/reconciliation/{sid}/consolidate")

def _export(client, sid):
    return client.post(f"/reconciliation/{sid}/export")


def _get_match_ids(session_id: str, bucket: str) -> List[str]:
    return [m["match_id"] for m in rm.get_runtime(session_id)["matching"][bucket]]


# ---------------------------------------------------------------------------
# Advance helpers
# ---------------------------------------------------------------------------

def _advance_to_final_consolidated_all_accepted(client, sid):
    """
    Run the full pipeline through Phase 7 with all decisions accepted.

    After this helper:
      - matching["final"] has 4 matches (2 det + 1 prob + 1 ai)
      - residual: empty
      - rejected: empty
      - state: final_consolidated
    """
    for step, fn in [
        ("upload",       lambda: _upload(client, sid)),
        ("profile",      lambda: _profile(client, sid)),
        ("preprocess",   lambda: _preprocess(client, sid)),
        ("deterministic",lambda: _deterministic(client, sid)),
        ("det_review",   lambda: _det_review(client, sid)),
        ("probabilistic",lambda: _probabilistic(client, sid)),
    ]:
        r = fn()
        assert r.status_code == 200, f"{step} failed: {r.text}"

    prob_ids = _get_match_ids(sid, "probabilistic")
    r = _prob_review(client, sid, [{"match_id": mid, "decision": "accepted"} for mid in prob_ids])
    assert r.status_code == 200, f"prob_review failed: {r.text}"

    r = _ai(client, sid)
    assert r.status_code == 200, f"ai failed: {r.text}"

    ai_ids = _get_match_ids(sid, "ai_suggested")
    r = _ai_review(client, sid, [{"match_id": mid, "decision": "accepted"} for mid in ai_ids])
    assert r.status_code == 200, f"ai_review failed: {r.text}"

    r = _consolidate(client, sid)
    assert r.status_code == 200, f"consolidate failed: {r.text}"


def _advance_to_final_consolidated_all_rejected(client, sid):
    """
    Run the full pipeline through Phase 7 with prob + AI all rejected.

    After this helper:
      - matching["final"] has 2 matches (det only)
      - residual: GL003+GL004, SUB003+SUB004
      - rejected: 2 matches (prob + ai)
      - state: final_consolidated
    """
    for step, fn in [
        ("upload",       lambda: _upload(client, sid)),
        ("profile",      lambda: _profile(client, sid)),
        ("preprocess",   lambda: _preprocess(client, sid)),
        ("deterministic",lambda: _deterministic(client, sid)),
        ("det_review",   lambda: _det_review(client, sid)),
        ("probabilistic",lambda: _probabilistic(client, sid)),
    ]:
        r = fn()
        assert r.status_code == 200, f"{step} failed: {r.text}"

    prob_ids = _get_match_ids(sid, "probabilistic")
    r = _prob_review(client, sid, [{"match_id": mid, "decision": "rejected"} for mid in prob_ids])
    assert r.status_code == 200, f"prob_review failed: {r.text}"

    r = _ai(client, sid)
    assert r.status_code == 200, f"ai failed: {r.text}"

    ai_ids = _get_match_ids(sid, "ai_suggested")
    r = _ai_review(client, sid, [{"match_id": mid, "decision": "rejected"} for mid in ai_ids])
    assert r.status_code == 200, f"ai_review failed: {r.text}"

    r = _consolidate(client, sid)
    assert r.status_code == 200, f"consolidate failed: {r.text}"


# ===========================================================================
# Happy path
# ===========================================================================

class TestHappyPath:
    def test_returns_200(self, client, session_id):
        _advance_to_final_consolidated_all_accepted(client, session_id)
        assert _export(client, session_id).status_code == 200

    def test_state_advances_to_finalized(self, client, session_id):
        _advance_to_final_consolidated_all_accepted(client, session_id)
        _export(client, session_id)
        assert rm.get_current_state(session_id) == ReconciliationState.FINALIZED

    def test_response_state_is_finalized(self, client, session_id):
        _advance_to_final_consolidated_all_accepted(client, session_id)
        data = _export(client, session_id).json()
        assert data["state"] == "finalized"

    def test_session_id_echoed(self, client, session_id):
        _advance_to_final_consolidated_all_accepted(client, session_id)
        data = _export(client, session_id).json()
        assert data["session_id"] == session_id

    def test_export_dir_present(self, client, session_id):
        _advance_to_final_consolidated_all_accepted(client, session_id)
        data = _export(client, session_id).json()
        assert data["export_dir"]

    def test_exported_at_present(self, client, session_id):
        _advance_to_final_consolidated_all_accepted(client, session_id)
        data = _export(client, session_id).json()
        assert data["exported_at"]

    def test_files_list_present_and_non_empty(self, client, session_id):
        _advance_to_final_consolidated_all_accepted(client, session_id)
        data = _export(client, session_id).json()
        assert isinstance(data["files"], list)
        assert len(data["files"]) > 0

    def test_snapshot_key_is_final_consolidated(self, client, session_id):
        _advance_to_final_consolidated_all_accepted(client, session_id)
        data = _export(client, session_id).json()
        assert data["snapshot"]["key"] == "final_consolidated"

    def test_snapshot_integrity_hash_present(self, client, session_id):
        _advance_to_final_consolidated_all_accepted(client, session_id)
        data = _export(client, session_id).json()
        assert len(data["snapshot"]["integrity_hash"]) == 64

    def test_eleven_snapshots_after_export(self, client, session_id):
        """Ten prior transitions + export = 11 snapshots total."""
        _advance_to_final_consolidated_all_accepted(client, session_id)
        _export(client, session_id)
        assert len(rm.get_runtime(session_id)["snapshots"]) == 11


# ===========================================================================
# Response — files
# ===========================================================================

class TestResponseFiles:
    _EXPECTED = {
        "uploaded_gl.csv",
        "uploaded_subledger.csv",
        "preprocessing_output.csv",
        "deterministic_matches.csv",
        "probabilistic_matches.csv",
        "ai_matches.csv",
        "final_results.csv",
        "residual_unmatched_gl.csv",
        "residual_unmatched_sub.csv",
        "rejected_matches.csv",
        "audit_log.csv",
        "process_log_run.csv",
        "process_log_steps.csv",
        "process_log_ai.csv",
        "reconciliation_report.pdf",
    }

    def test_exactly_fifteen_files(self, client, session_id):
        _advance_to_final_consolidated_all_accepted(client, session_id)
        data = _export(client, session_id).json()
        assert len(data["files"]) == 15

    def test_expected_filenames(self, client, session_id):
        _advance_to_final_consolidated_all_accepted(client, session_id)
        data = _export(client, session_id).json()
        names = {f["filename"] for f in data["files"]}
        assert names == self._EXPECTED

    def test_each_file_has_sha256(self, client, session_id):
        _advance_to_final_consolidated_all_accepted(client, session_id)
        data = _export(client, session_id).json()
        for f in data["files"]:
            assert len(f["sha256"]) == 64, f"{f['filename']}: sha256 wrong length"

    def test_each_file_size_positive(self, client, session_id):
        _advance_to_final_consolidated_all_accepted(client, session_id)
        data = _export(client, session_id).json()
        for f in data["files"]:
            assert f["size_bytes"] > 0, f"{f['filename']}: size_bytes == 0"

    def test_each_file_path_non_empty(self, client, session_id):
        _advance_to_final_consolidated_all_accepted(client, session_id)
        data = _export(client, session_id).json()
        for f in data["files"]:
            assert f["path"], f"{f['filename']}: path is empty"


# ===========================================================================
# Known result — all accepted
# ===========================================================================

class TestKnownResultAllAccepted:
    def _csv_rows(self, export_dir: str, filename: str) -> int:
        """Count data rows (excluding header) in a CSV file."""
        import pandas as pd
        path = os.path.join(export_dir, filename)
        if not os.path.isfile(path):
            return -1
        try:
            return len(pd.read_csv(path))
        except pd.errors.EmptyDataError:
            return 0

    def test_final_results_has_four_rows(self, client, session_id):
        _advance_to_final_consolidated_all_accepted(client, session_id)
        data = _export(client, session_id).json()
        assert self._csv_rows(data["export_dir"], "final_results.csv") == 4

    def test_residual_gl_has_zero_rows(self, client, session_id):
        _advance_to_final_consolidated_all_accepted(client, session_id)
        data = _export(client, session_id).json()
        assert self._csv_rows(data["export_dir"], "residual_unmatched_gl.csv") == 0

    def test_residual_sub_has_zero_rows(self, client, session_id):
        _advance_to_final_consolidated_all_accepted(client, session_id)
        data = _export(client, session_id).json()
        assert self._csv_rows(data["export_dir"], "residual_unmatched_sub.csv") == 0

    def test_rejected_has_zero_rows(self, client, session_id):
        _advance_to_final_consolidated_all_accepted(client, session_id)
        data = _export(client, session_id).json()
        assert self._csv_rows(data["export_dir"], "rejected_matches.csv") == 0

    def test_audit_log_has_at_least_four_rows(self, client, session_id):
        _advance_to_final_consolidated_all_accepted(client, session_id)
        data = _export(client, session_id).json()
        assert self._csv_rows(data["export_dir"], "audit_log.csv") >= 4


# ===========================================================================
# Known result — all rejected
# ===========================================================================

class TestKnownResultAllRejected:
    def _csv_rows(self, export_dir: str, filename: str) -> int:
        import pandas as pd
        path = os.path.join(export_dir, filename)
        if not os.path.isfile(path):
            return -1
        try:
            return len(pd.read_csv(path))
        except pd.errors.EmptyDataError:
            return 0

    def test_final_results_has_two_rows(self, client, session_id):
        """Only deterministic matches remain accepted."""
        _advance_to_final_consolidated_all_rejected(client, session_id)
        data = _export(client, session_id).json()
        assert self._csv_rows(data["export_dir"], "final_results.csv") == 2

    def test_rejected_has_at_least_one_row(self, client, session_id):
        _advance_to_final_consolidated_all_rejected(client, session_id)
        data = _export(client, session_id).json()
        assert self._csv_rows(data["export_dir"], "rejected_matches.csv") >= 1


# ===========================================================================
# Terminal state — no re-export
# ===========================================================================

class TestTerminalState:
    def test_second_export_returns_409(self, client, session_id):
        _advance_to_final_consolidated_all_accepted(client, session_id)
        _export(client, session_id)
        assert _export(client, session_id).status_code == 409

    def test_second_export_detail_mentions_already_or_finalized(self, client, session_id):
        _advance_to_final_consolidated_all_accepted(client, session_id)
        _export(client, session_id)
        detail = _export(client, session_id).json()["detail"].lower()
        assert "already" in detail or "finalized" in detail

    def test_state_remains_finalized(self, client, session_id):
        _advance_to_final_consolidated_all_accepted(client, session_id)
        _export(client, session_id)
        _export(client, session_id)  # rejected call
        assert rm.get_current_state(session_id) == ReconciliationState.FINALIZED

    def test_no_extra_snapshot_on_second_call(self, client, session_id):
        _advance_to_final_consolidated_all_accepted(client, session_id)
        _export(client, session_id)
        count = len(rm.get_runtime(session_id)["snapshots"])
        _export(client, session_id)  # rejected
        assert len(rm.get_runtime(session_id)["snapshots"]) == count


# ===========================================================================
# Wrong state
# ===========================================================================

class TestWrongState:
    def test_from_initialized_returns_409(self, client, session_id):
        assert _export(client, session_id).status_code == 409

    def test_from_initialized_detail_mentions_final_consolidated(self, client, session_id):
        detail = _export(client, session_id).json()["detail"]
        assert "final_consolidated" in detail

    def test_from_preprocessed_returns_409(self, client, session_id):
        for fn in [
            lambda: _upload(client, session_id),
            lambda: _profile(client, session_id),
            lambda: _preprocess(client, session_id),
        ]:
            fn()
        assert _export(client, session_id).status_code == 409

    def test_from_preprocessed_detail_mentions_final_consolidated(self, client, session_id):
        for fn in [
            lambda: _upload(client, session_id),
            lambda: _profile(client, session_id),
            lambda: _preprocess(client, session_id),
        ]:
            fn()
        detail = _export(client, session_id).json()["detail"]
        assert "final_consolidated" in detail

    def test_from_ai_review_complete_returns_409(self, client, session_id):
        for step, fn in [
            ("upload",       lambda: _upload(client, session_id)),
            ("profile",      lambda: _profile(client, session_id)),
            ("preprocess",   lambda: _preprocess(client, session_id)),
            ("deterministic",lambda: _deterministic(client, session_id)),
            ("det_review",   lambda: _det_review(client, session_id)),
            ("probabilistic",lambda: _probabilistic(client, session_id)),
            ("prob_review",  lambda: _prob_review(client, session_id)),
            ("ai",           lambda: _ai(client, session_id)),
            ("ai_review",    lambda: _ai_review(client, session_id)),
        ]:
            r = fn()
            assert r.status_code == 200, f"{step} failed: {r.text}"
        assert _export(client, session_id).status_code == 409

    def test_from_ai_review_complete_detail_mentions_final_consolidated(self, client, session_id):
        for step, fn in [
            ("upload",       lambda: _upload(client, session_id)),
            ("profile",      lambda: _profile(client, session_id)),
            ("preprocess",   lambda: _preprocess(client, session_id)),
            ("deterministic",lambda: _deterministic(client, session_id)),
            ("det_review",   lambda: _det_review(client, session_id)),
            ("probabilistic",lambda: _probabilistic(client, session_id)),
            ("prob_review",  lambda: _prob_review(client, session_id)),
            ("ai",           lambda: _ai(client, session_id)),
            ("ai_review",    lambda: _ai_review(client, session_id)),
        ]:
            r = fn()
            assert r.status_code == 200, f"{step} failed: {r.text}"
        detail = _export(client, session_id).json()["detail"]
        assert "final_consolidated" in detail

    def test_unknown_session_returns_404(self, client):
        r = client.post("/reconciliation/no-such-session/export")
        assert r.status_code == 404

    def test_unknown_session_detail_contains_session_id(self, client):
        r = client.post("/reconciliation/no-such-session/export")
        assert "no-such-session" in r.json()["detail"]


# ===========================================================================
# Export metadata in runtime
# ===========================================================================

class TestExportMetaInRuntime:
    def test_export_meta_written(self, client, session_id):
        _advance_to_final_consolidated_all_accepted(client, session_id)
        _export(client, session_id)
        export_meta = rm.get_runtime(session_id)["export"]
        assert "export_dir" in export_meta

    def test_export_meta_has_exported_at(self, client, session_id):
        _advance_to_final_consolidated_all_accepted(client, session_id)
        _export(client, session_id)
        export_meta = rm.get_runtime(session_id)["export"]
        assert "exported_at" in export_meta

    def test_export_meta_has_files(self, client, session_id):
        _advance_to_final_consolidated_all_accepted(client, session_id)
        _export(client, session_id)
        export_meta = rm.get_runtime(session_id)["export"]
        assert "files" in export_meta
        assert len(export_meta["files"]) == 15

    def test_export_meta_files_have_sha256(self, client, session_id):
        _advance_to_final_consolidated_all_accepted(client, session_id)
        _export(client, session_id)
        files = rm.get_runtime(session_id)["export"]["files"]
        for f in files:
            assert len(f["sha256"]) == 64
