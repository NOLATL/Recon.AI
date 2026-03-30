"""
Phase 1 — POST /reconciliation/{session_id}/upload

Tests every explicit requirement:

  [Happy path]
  - All three valid files accepted
  - State advances to files_loaded
  - Row counts match file content
  - Schema hashes present and deterministic
  - Snapshot written before transition (key == 'initialized')
  - raw_data populated in runtime with correct types
  - Validation summary in response shows is_valid=True for all files

  [Missing columns]
  - Missing a required GL column → 422, column named in error
  - Missing a required Subledger column → 422
  - Missing a required CoA column → 422
  - Multiple missing columns reported together

  [Type mismatch — no silent coercion]
  - GL amount column contains a non-numeric string → 422 with row indices
  - GL transaction_date column contains an unparseable date → 422 with row indices
  - GL exception_flag column contains an invalid bool value → 422 with row indices
  - CoA materiality_threshold contains non-numeric → 422

  [Error structure]
  - 422 detail is a list of per-file error objects
  - Each error object has file_key, missing_columns, column_errors
  - column_errors includes failing_row_count and sample_bad_values
  - Only the failing file appears in error detail

  [Illegal state transition]
  - Upload in files_loaded state (not initialized) → 409
  - Upload to unknown session → 404

  [State invariants]
  - Failed upload does NOT advance state
  - Failed upload does NOT create a snapshot
  - Failed upload does NOT write raw_data
"""

import csv
import io
from typing import Dict, List, Any

import pytest

import src.core.runtime_manager as rm
from src.core.state_machine import ReconciliationState


# ---------------------------------------------------------------------------
# CSV builders
# ---------------------------------------------------------------------------

def _make_csv(rows: Dict[str, List[Any]]) -> bytes:
    """Build a minimal CSV as bytes from column → list of values."""
    buf = io.StringIO()
    cols = list(rows.keys())
    writer = csv.DictWriter(buf, fieldnames=cols)
    writer.writeheader()
    n = len(next(iter(rows.values())))
    for i in range(n):
        writer.writerow({col: rows[col][i] for col in cols})
    return buf.getvalue().encode("utf-8")


# Minimal valid single-row content for each file
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
    "account_code":         ["ACCT_100", "ACCT_101"],
    "account_name":         ["Cash", "Accounts Payable"],
    "account_type":         ["Asset", "Liability"],
    "materiality_threshold":["10000.00", "5000.00"],
}


def _valid_files():
    """Return a files dict with all three valid CSVs."""
    return {
        "gl":                ("GL.csv",                _make_csv(_VALID_GL),  "text/csv"),
        "chart_of_accounts": ("Chart_of_Accounts.csv", _make_csv(_VALID_COA), "text/csv"),
        "subledger":         ("Subledger.csv",         _make_csv(_VALID_SUB), "text/csv"),
    }


def _post_upload(client, session_id, files):
    return client.post(f"/reconciliation/{session_id}/upload", files=files)


def _drop_column(data: dict, col: str) -> dict:
    return {k: v for k, v in data.items() if k != col}


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------

class TestHappyPath:
    def test_returns_200(self, client, session_id):
        resp = _post_upload(client, session_id, _valid_files())
        assert resp.status_code == 200, resp.text

    def test_state_advances_to_files_loaded(self, client, session_id):
        _post_upload(client, session_id, _valid_files())
        assert rm.get_current_state(session_id) == ReconciliationState.FILES_LOADED

    def test_response_state_is_files_loaded(self, client, session_id):
        data = _post_upload(client, session_id, _valid_files()).json()
        assert data["state"] == "files_loaded"

    def test_row_counts_in_response(self, client, session_id):
        data = _post_upload(client, session_id, _valid_files()).json()
        assert data["row_counts"]["gl"] == 2
        assert data["row_counts"]["subledger"] == 2
        assert data["row_counts"]["chart_of_accounts"] == 2

    def test_validation_summary_all_valid(self, client, session_id):
        data = _post_upload(client, session_id, _valid_files()).json()
        for key in ("gl", "subledger", "chart_of_accounts"):
            assert data["validation"][key]["is_valid"] is True

    def test_schema_hashes_present(self, client, session_id):
        data = _post_upload(client, session_id, _valid_files()).json()
        for key in ("gl", "subledger", "chart_of_accounts"):
            assert len(data["validation"][key]["schema_hash"]) == 64  # SHA-256

    def test_schema_hash_is_deterministic(self, client):
        """Same file content uploaded twice must produce the same hash."""
        sid1 = rm.create_session()
        sid2 = rm.create_session()
        h1 = _post_upload(client, sid1, _valid_files()).json()["validation"]["gl"]["schema_hash"]
        h2 = _post_upload(client, sid2, _valid_files()).json()["validation"]["gl"]["schema_hash"]
        assert h1 == h2

    def test_snapshot_key_is_initialized(self, client, session_id):
        """Snapshot was captured before the transition, so its key is 'initialized'."""
        data = _post_upload(client, session_id, _valid_files()).json()
        assert data["snapshot"]["key"] == "initialized"

    def test_snapshot_integrity_hash_present(self, client, session_id):
        data = _post_upload(client, session_id, _valid_files()).json()
        assert len(data["snapshot"]["integrity_hash"]) == 64

    def test_raw_data_written_to_runtime(self, client, session_id):
        _post_upload(client, session_id, _valid_files())
        runtime = rm.get_runtime(session_id)
        assert runtime["raw_data"]["gl"] is not None
        assert runtime["raw_data"]["subledger"] is not None
        assert runtime["raw_data"]["chart_of_accounts"] is not None

    def test_raw_data_row_count_matches(self, client, session_id):
        _post_upload(client, session_id, _valid_files())
        runtime = rm.get_runtime(session_id)
        assert len(runtime["raw_data"]["gl"]) == 2
        assert len(runtime["raw_data"]["subledger"]) == 2

    def test_one_snapshot_created(self, client, session_id):
        _post_upload(client, session_id, _valid_files())
        assert len(rm.get_session_snapshots(session_id)) == 1


# ---------------------------------------------------------------------------
# Missing columns
# ---------------------------------------------------------------------------

class TestMissingColumns:
    def _upload_with_bad_gl(self, client, session_id, gl_data: dict):
        files = _valid_files()
        files["gl"] = ("GL.csv", _make_csv(gl_data), "text/csv")
        return _post_upload(client, session_id, files)

    def _upload_with_bad_sub(self, client, session_id, sub_data: dict):
        files = _valid_files()
        files["subledger"] = ("Subledger.csv", _make_csv(sub_data), "text/csv")
        return _post_upload(client, session_id, files)

    def _upload_with_bad_coa(self, client, session_id, coa_data: dict):
        files = _valid_files()
        files["chart_of_accounts"] = ("Chart_of_Accounts.csv", _make_csv(coa_data), "text/csv")
        return _post_upload(client, session_id, files)

    def test_missing_gl_amount_returns_422(self, client, session_id):
        resp = self._upload_with_bad_gl(client, session_id, _drop_column(_VALID_GL, "amount"))
        assert resp.status_code == 422

    def test_missing_gl_amount_named_in_error(self, client, session_id):
        resp = self._upload_with_bad_gl(client, session_id, _drop_column(_VALID_GL, "amount"))
        gl_err = next(e for e in resp.json()["detail"] if e["file_key"] == "gl")
        assert "amount" in gl_err["missing_columns"]

    def test_missing_gl_vendor_name(self, client, session_id):
        resp = self._upload_with_bad_gl(client, session_id, _drop_column(_VALID_GL, "vendor_name"))
        assert resp.status_code == 422
        gl_err = next(e for e in resp.json()["detail"] if e["file_key"] == "gl")
        assert "vendor_name" in gl_err["missing_columns"]

    def test_missing_subledger_reference_id(self, client, session_id):
        resp = self._upload_with_bad_sub(client, session_id, _drop_column(_VALID_SUB, "reference_id"))
        assert resp.status_code == 422
        sub_err = next(e for e in resp.json()["detail"] if e["file_key"] == "subledger")
        assert "reference_id" in sub_err["missing_columns"]

    def test_missing_coa_materiality_threshold(self, client, session_id):
        resp = self._upload_with_bad_coa(client, session_id, _drop_column(_VALID_COA, "materiality_threshold"))
        assert resp.status_code == 422
        coa_err = next(e for e in resp.json()["detail"] if e["file_key"] == "chart_of_accounts")
        assert "materiality_threshold" in coa_err["missing_columns"]

    def test_multiple_missing_columns_all_reported(self, client, session_id):
        bad_gl = _drop_column(_drop_column(_VALID_GL, "amount"), "currency")
        resp = self._upload_with_bad_gl(client, session_id, bad_gl)
        assert resp.status_code == 422
        gl_err = next(e for e in resp.json()["detail"] if e["file_key"] == "gl")
        assert "amount" in gl_err["missing_columns"]
        assert "currency" in gl_err["missing_columns"]

    def test_only_failing_file_in_error_detail(self, client, session_id):
        """If only GL fails, subledger and CoA should NOT appear in detail."""
        resp = self._upload_with_bad_gl(client, session_id, _drop_column(_VALID_GL, "amount"))
        file_keys_in_error = {e["file_key"] for e in resp.json()["detail"]}
        assert "gl" in file_keys_in_error
        assert "subledger" not in file_keys_in_error
        assert "chart_of_accounts" not in file_keys_in_error

    def test_missing_column_does_not_advance_state(self, client, session_id):
        self._upload_with_bad_gl(client, session_id, _drop_column(_VALID_GL, "amount"))
        assert rm.get_current_state(session_id) == ReconciliationState.INITIALIZED

    def test_missing_column_does_not_create_snapshot(self, client, session_id):
        self._upload_with_bad_gl(client, session_id, _drop_column(_VALID_GL, "amount"))
        assert len(rm.get_session_snapshots(session_id)) == 0

    def test_missing_column_does_not_write_raw_data(self, client, session_id):
        self._upload_with_bad_gl(client, session_id, _drop_column(_VALID_GL, "amount"))
        runtime = rm.get_runtime(session_id)
        assert runtime["raw_data"]["gl"] is None


# ---------------------------------------------------------------------------
# Type mismatch — no silent coercion
# ---------------------------------------------------------------------------

class TestTypeMismatch:
    def _bad_gl_upload(self, client, session_id, gl_override: dict):
        data = {**_VALID_GL, **gl_override}
        files = _valid_files()
        files["gl"] = ("GL.csv", _make_csv(data), "text/csv")
        return _post_upload(client, session_id, files)

    def _bad_coa_upload(self, client, session_id, coa_override: dict):
        data = {**_VALID_COA, **coa_override}
        files = _valid_files()
        files["chart_of_accounts"] = ("Chart_of_Accounts.csv", _make_csv(data), "text/csv")
        return _post_upload(client, session_id, files)

    # --- float64 ---

    def test_non_numeric_amount_returns_422(self, client, session_id):
        resp = self._bad_gl_upload(client, session_id, {"amount": ["100.00", "NOT_A_NUMBER"]})
        assert resp.status_code == 422

    def test_non_numeric_amount_error_detail(self, client, session_id):
        resp = self._bad_gl_upload(client, session_id, {"amount": ["100.00", "NOT_A_NUMBER"]})
        gl_err = next(e for e in resp.json()["detail"] if e["file_key"] == "gl")
        col_err = next(e for e in gl_err["column_errors"] if e["column"] == "amount")
        assert col_err["expected_dtype"] == "float64"
        assert col_err["failing_row_count"] >= 1
        assert "NOT_A_NUMBER" in col_err["sample_bad_values"]

    def test_non_numeric_amount_reports_row_index(self, client, session_id):
        resp = self._bad_gl_upload(client, session_id, {"amount": ["100.00", "BAD"]})
        gl_err = next(e for e in resp.json()["detail"] if e["file_key"] == "gl")
        col_err = next(e for e in gl_err["column_errors"] if e["column"] == "amount")
        assert len(col_err["failing_row_indices"]) >= 1

    def test_non_numeric_coa_threshold_returns_422(self, client, session_id):
        # "N/A" is in pandas' default NA sentinel list and reads as NaN (allowed).
        # Use a string pandas cannot interpret as numeric or missing.
        resp = self._bad_coa_upload(client, session_id, {"materiality_threshold": ["10000", "INVALID"]})
        assert resp.status_code == 422
        coa_err = next(e for e in resp.json()["detail"] if e["file_key"] == "chart_of_accounts")
        col_err = next(e for e in coa_err["column_errors"] if e["column"] == "materiality_threshold")
        assert col_err["expected_dtype"] == "float64"

    # --- datetime ---

    def test_invalid_date_returns_422(self, client, session_id):
        resp = self._bad_gl_upload(client, session_id, {"transaction_date": ["2024-01-15", "NOT-A-DATE"]})
        assert resp.status_code == 422

    def test_invalid_date_error_detail(self, client, session_id):
        resp = self._bad_gl_upload(client, session_id, {"transaction_date": ["2024-01-15", "NOT-A-DATE"]})
        gl_err = next(e for e in resp.json()["detail"] if e["file_key"] == "gl")
        col_err = next(e for e in gl_err["column_errors"] if e["column"] == "transaction_date")
        assert col_err["expected_dtype"] == "datetime64[ns]"
        assert "NOT-A-DATE" in col_err["sample_bad_values"]

    # --- bool ---

    def test_invalid_bool_returns_422(self, client, session_id):
        resp = self._bad_gl_upload(client, session_id, {"exception_flag": ["False", "yes"]})
        assert resp.status_code == 422

    def test_invalid_bool_error_detail(self, client, session_id):
        resp = self._bad_gl_upload(client, session_id, {"exception_flag": ["False", "yes"]})
        gl_err = next(e for e in resp.json()["detail"] if e["file_key"] == "gl")
        col_err = next(e for e in gl_err["column_errors"] if e["column"] == "exception_flag")
        assert col_err["expected_dtype"] == "bool"
        assert "yes" in col_err["sample_bad_values"]

    def test_invalid_bool_arbitrary_string(self, client, session_id):
        """'enabled', 'no', 'Y' are not valid bool representations."""
        resp = self._bad_gl_upload(client, session_id, {"exception_flag": ["False", "enabled"]})
        assert resp.status_code == 422

    def test_valid_bool_representations_accepted(self, client, session_id):
        """True, False, 1, 0 and their string variants are all valid."""
        for flag_value in ("True", "False", "true", "false", "1", "0"):
            sid = rm.create_session()
            resp = self._bad_gl_upload(client, sid, {"exception_flag": ["True", flag_value]})
            assert resp.status_code == 200, f"'{flag_value}' should be a valid bool"

    # --- multiple type errors collected together ---

    def test_multiple_column_errors_all_reported(self, client, session_id):
        """Both a bad amount and a bad date in the same file → both errors returned."""
        resp = self._bad_gl_upload(client, session_id, {
            "amount":           ["100.00", "BAD"],
            "transaction_date": ["2024-01-15", "NOT-A-DATE"],
        })
        assert resp.status_code == 422
        gl_err = next(e for e in resp.json()["detail"] if e["file_key"] == "gl")
        error_cols = {e["column"] for e in gl_err["column_errors"]}
        assert "amount" in error_cols
        assert "transaction_date" in error_cols

    # --- state invariants on type mismatch ---

    def test_type_mismatch_does_not_advance_state(self, client, session_id):
        self._bad_gl_upload(client, session_id, {"amount": ["100.00", "BAD"]})
        assert rm.get_current_state(session_id) == ReconciliationState.INITIALIZED

    def test_type_mismatch_does_not_create_snapshot(self, client, session_id):
        self._bad_gl_upload(client, session_id, {"amount": ["100.00", "BAD"]})
        assert len(rm.get_session_snapshots(session_id)) == 0

    def test_type_mismatch_does_not_write_raw_data(self, client, session_id):
        self._bad_gl_upload(client, session_id, {"amount": ["100.00", "BAD"]})
        runtime = rm.get_runtime(session_id)
        assert runtime["raw_data"]["gl"] is None


# ---------------------------------------------------------------------------
# Illegal state transition
# ---------------------------------------------------------------------------

class TestIllegalStateTransition:
    def test_upload_to_unknown_session_returns_404(self, client):
        resp = _post_upload(client, "nonexistent-id", _valid_files())
        assert resp.status_code == 404

    def test_upload_when_already_files_loaded_returns_409(self, client, session_id):
        # First upload succeeds
        _post_upload(client, session_id, _valid_files())
        assert rm.get_current_state(session_id) == ReconciliationState.FILES_LOADED

        # Second upload must be rejected — state is no longer initialized
        resp = _post_upload(client, session_id, _valid_files())
        assert resp.status_code == 409

    def test_409_detail_mentions_current_state(self, client, session_id):
        _post_upload(client, session_id, _valid_files())
        resp = _post_upload(client, session_id, _valid_files())
        assert "files_loaded" in resp.json()["detail"]

    def test_second_upload_does_not_create_extra_snapshot(self, client, session_id):
        _post_upload(client, session_id, _valid_files())
        snapshot_count_after_first = len(rm.get_session_snapshots(session_id))

        _post_upload(client, session_id, _valid_files())  # rejected
        assert len(rm.get_session_snapshots(session_id)) == snapshot_count_after_first

    @pytest.mark.parametrize("target_state", [
        "profiled",
        "preprocessed",
        "deterministic_complete",
    ])
    def test_upload_rejected_in_later_states(self, client, target_state):
        """Upload must be rejected in any state other than initialized."""
        sid = rm.create_session()
        # Manually walk forward through states to reach a later one
        from src.core.state_machine import ReconciliationState as RS
        state_map = {
            "profiled":               [RS.FILES_LOADED, RS.COLUMN_MAPPING_COMPLETE, RS.PROFILED],
            "preprocessed":           [RS.FILES_LOADED, RS.COLUMN_MAPPING_COMPLETE, RS.PROFILED, RS.PREPROCESSED],
            "deterministic_complete": [RS.FILES_LOADED, RS.COLUMN_MAPPING_COMPLETE, RS.PROFILED, RS.PREPROCESSED, RS.MATCHING_CONFIGURED, RS.DETERMINISTIC_COMPLETE],
        }
        for state in state_map[target_state]:
            rm.advance_state(sid, state)

        resp = _post_upload(client, sid, _valid_files())
        assert resp.status_code == 409
