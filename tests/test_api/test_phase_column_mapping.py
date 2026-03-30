"""
Column Mapping endpoints — POST /reconciliation/{session_id}/analyze-columns
                           POST /reconciliation/{session_id}/confirm-columns

[analyze-columns — Happy path]
- Returns 200 in files_loaded state
- response state == 'files_loaded'
- session_id echoed
- side_a_suggestions and side_b_suggestions are lists
- analysis_narrative is present (may be empty if AI unavailable)
- No state change after analyze-columns

[analyze-columns — Wrong state]
- 409 if state is 'initialized' (no files)
- 404 for unknown session

[confirm-columns — Happy path]
- Returns 200 with valid column map
- State advances to 'column_mapping_complete'
- Snapshot captured (snapshot.key == 'files_loaded')
- column_map persisted in runtime

[confirm-columns — Validation errors → 422]
- Missing required role 'id' on side_a
- Missing required role 'vendor' on side_b
- Column name not present in uploaded file

[confirm-columns — Wrong state]
- 409 if already in column_mapping_complete
- 409 if in any other post-files_loaded state
- 404 for unknown session
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
        writer.writerow({c: ("" if rows[c][i] is None else rows[c][i]) for c in cols})
    return buf.getvalue().encode("utf-8")


# ---------------------------------------------------------------------------
# Minimal valid data
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

# A valid column map matching the above files
_VALID_COLUMN_MAP = {
    "column_map": {
        "side_a_label": "GL",
        "side_b_label": "Subledger",
        "side_a": {
            "id":     "gl_id",
            "vendor": "vendor_name",
            "amount": "amount",
            "date":   "transaction_date",
            "entity": "entity",
            "currency": "currency",
        },
        "side_b": {
            "id":     "subledger_id",
            "vendor": "vendor_name",
            "amount": "amount",
            "date":   "transaction_date",
            "entity": "entity",
            "currency": "currency",
        },
    }
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _upload(client, session_id):
    return client.post(
        f"/reconciliation/{session_id}/upload",
        files={
            "gl":                ("GL.csv",                _make_csv(_VALID_GL),  "text/csv"),
            "chart_of_accounts": ("Chart_of_Accounts.csv", _make_csv(_VALID_COA), "text/csv"),
            "subledger":         ("Subledger.csv",         _make_csv(_VALID_SUB), "text/csv"),
        },
    )


def _advance_to_files_loaded(client, session_id):
    resp = _upload(client, session_id)
    assert resp.status_code == 200, f"Upload failed: {resp.text}"
    return resp


def _analyze(client, session_id):
    return client.post(f"/reconciliation/{session_id}/analyze-columns")


def _confirm(client, session_id, body=None):
    return client.post(
        f"/reconciliation/{session_id}/confirm-columns",
        json=(body or _VALID_COLUMN_MAP),
    )


# ---------------------------------------------------------------------------
# analyze-columns
# ---------------------------------------------------------------------------

class TestAnalyzeColumns:
    def test_returns_200_in_files_loaded(self, client, session_id):
        _advance_to_files_loaded(client, session_id)
        assert _analyze(client, session_id).status_code == 200

    def test_state_unchanged_after_analyze(self, client, session_id):
        _advance_to_files_loaded(client, session_id)
        _analyze(client, session_id)
        assert rm.get_current_state(session_id) == ReconciliationState.FILES_LOADED

    def test_response_contains_session_id(self, client, session_id):
        _advance_to_files_loaded(client, session_id)
        data = _analyze(client, session_id).json()
        assert data["session_id"] == session_id

    def test_response_has_side_a_and_b_suggestions(self, client, session_id):
        _advance_to_files_loaded(client, session_id)
        data = _analyze(client, session_id).json()
        assert isinstance(data["side_a_suggestions"], list)
        assert isinstance(data["side_b_suggestions"], list)

    def test_suggestions_cover_all_gl_columns(self, client, session_id):
        _advance_to_files_loaded(client, session_id)
        data = _analyze(client, session_id).json()
        # All columns in the uploaded GL file must appear in side_a_suggestions
        detected_cols = {s["column_name"] for s in data["side_a_suggestions"]}
        assert set(_VALID_GL.keys()).issubset(detected_cols)

    def test_analysis_narrative_present(self, client, session_id):
        _advance_to_files_loaded(client, session_id)
        data = _analyze(client, session_id).json()
        assert "analysis_narrative" in data

    def test_409_from_initialized_state(self, client, session_id):
        # Session is initialized (no upload) — should 409
        resp = _analyze(client, session_id)
        assert resp.status_code == 409

    def test_404_unknown_session(self, client):
        resp = client.post("/reconciliation/nonexistent-id/analyze-columns")
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# confirm-columns
# ---------------------------------------------------------------------------

class TestConfirmColumns:
    def test_returns_200_with_valid_map(self, client, session_id):
        _advance_to_files_loaded(client, session_id)
        assert _confirm(client, session_id).status_code == 200

    def test_state_advances_to_column_mapping_complete(self, client, session_id):
        _advance_to_files_loaded(client, session_id)
        _confirm(client, session_id)
        assert rm.get_current_state(session_id) == ReconciliationState.COLUMN_MAPPING_COMPLETE

    def test_response_state_is_column_mapping_complete(self, client, session_id):
        _advance_to_files_loaded(client, session_id)
        data = _confirm(client, session_id).json()
        assert data["state"] == "column_mapping_complete"

    def test_response_echoes_session_id(self, client, session_id):
        _advance_to_files_loaded(client, session_id)
        data = _confirm(client, session_id).json()
        assert data["session_id"] == session_id

    def test_snapshot_captured_with_key_files_loaded(self, client, session_id):
        _advance_to_files_loaded(client, session_id)
        data = _confirm(client, session_id).json()
        assert data["snapshot"]["key"] == "files_loaded"

    def test_snapshot_has_integrity_hash(self, client, session_id):
        _advance_to_files_loaded(client, session_id)
        data = _confirm(client, session_id).json()
        h = data["snapshot"]["integrity_hash"]
        assert len(h) == 64 and all(c in "0123456789abcdef" for c in h)

    def test_column_map_persisted_in_runtime(self, client, session_id):
        _advance_to_files_loaded(client, session_id)
        _confirm(client, session_id)
        runtime = rm.get_runtime(session_id)
        assert runtime["config"]["column_map"]["side_a"]["id"] == "gl_id"

    def test_422_missing_required_role_id_on_side_a(self, client, session_id):
        _advance_to_files_loaded(client, session_id)
        bad_map = {
            "column_map": {
                "side_a_label": "GL",
                "side_b_label": "Subledger",
                "side_a": {
                    # id is missing
                    "vendor": "vendor_name",
                    "amount": "amount",
                },
                "side_b": {
                    "id":     "subledger_id",
                    "vendor": "vendor_name",
                    "amount": "amount",
                },
            }
        }
        resp = _confirm(client, session_id, bad_map)
        assert resp.status_code == 422

    def test_422_missing_required_role_vendor_on_side_b(self, client, session_id):
        _advance_to_files_loaded(client, session_id)
        bad_map = {
            "column_map": {
                "side_a_label": "GL",
                "side_b_label": "Subledger",
                "side_a": {
                    "id":     "gl_id",
                    "vendor": "vendor_name",
                    "amount": "amount",
                },
                "side_b": {
                    "id":     "subledger_id",
                    # vendor is missing
                    "amount": "amount",
                },
            }
        }
        resp = _confirm(client, session_id, bad_map)
        assert resp.status_code == 422

    def test_422_column_name_not_in_file(self, client, session_id):
        _advance_to_files_loaded(client, session_id)
        bad_map = {
            "column_map": {
                "side_a_label": "GL",
                "side_b_label": "Subledger",
                "side_a": {
                    "id":     "nonexistent_column",   # doesn't exist in GL file
                    "vendor": "vendor_name",
                    "amount": "amount",
                },
                "side_b": {
                    "id":     "subledger_id",
                    "vendor": "vendor_name",
                    "amount": "amount",
                },
            }
        }
        resp = _confirm(client, session_id, bad_map)
        assert resp.status_code == 422

    def test_409_already_in_column_mapping_complete(self, client, session_id):
        _advance_to_files_loaded(client, session_id)
        _confirm(client, session_id)
        resp = _confirm(client, session_id)
        assert resp.status_code == 409
        assert "column_mapping_complete" in resp.json()["detail"].lower()

    def test_409_in_wrong_state(self, client, session_id):
        # initialized → no files uploaded, wrong state for confirm
        resp = _confirm(client, session_id)
        assert resp.status_code == 409

    def test_404_unknown_session(self, client):
        resp = client.post(
            "/reconciliation/nonexistent-id/confirm-columns",
            json=_VALID_COLUMN_MAP,
        )
        assert resp.status_code == 404
