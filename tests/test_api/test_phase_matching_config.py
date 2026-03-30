"""
Matching Config endpoints — POST /reconciliation/{session_id}/suggest-matching-config
                             POST /reconciliation/{session_id}/confirm-matching-config

[suggest-matching-config — Happy path]
- Returns 200 in preprocessed state
- response state == 'preprocessed'
- session_id echoed
- deterministic_scenarios is a non-empty list
- probabilistic config has weights dict and threshold
- No state change after suggest

[suggest-matching-config — Wrong state]
- 409 if not in preprocessed state
- 404 for unknown session

[confirm-matching-config — Happy path]
- Returns 200 with valid config
- State advances to 'matching_configured'
- Snapshot captured (snapshot.key == 'preprocessed')
- matching_config persisted in runtime

[confirm-matching-config — Validation errors → 422]
- Probabilistic weights not summing to 1.0
- Threshold out of range
- Deterministic scenario missing 'vendor' in match_fields
- Deterministic scenario missing 'amount' in match_fields

[confirm-matching-config — Wrong state]
- 409 if already in matching_configured
- 409 if in wrong state
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

_VALID_CONFIG = {
    "deterministic": [
        {
            "scenario_id": 1,
            "description": "Exact match",
            "match_fields": ["vendor", "amount", "date", "entity"],
            "date_tolerance_days": None,
            "confidence_score": 1.0,
        },
        {
            "scenario_id": 2,
            "description": "Vendor + amount + 30-day window",
            "match_fields": ["vendor", "amount", "entity"],
            "date_tolerance_days": 30,
            "confidence_score": 0.95,
        },
    ],
    "probabilistic": {
        "weights": {"vendor": 0.45, "amount": 0.40, "date": 0.15},
        "threshold": 0.80,
        "date_tolerance_days": 30,
        "amount_pct_tolerance": 0.10,
        "amount_abs_tolerance": 5.00,
    },
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


def _advance_to_preprocessed(client, session_id):
    """Advance session to PREPROCESSED state (bypassing new AI-driven steps)."""
    resp = _upload(client, session_id)
    assert resp.status_code == 200
    rm.advance_state(session_id, ReconciliationState.COLUMN_MAPPING_COMPLETE)
    resp = client.post(f"/reconciliation/{session_id}/profile")
    assert resp.status_code == 200
    resp = client.post(f"/reconciliation/{session_id}/preprocess")
    assert resp.status_code == 200


def _suggest(client, session_id):
    return client.post(f"/reconciliation/{session_id}/suggest-matching-config")


def _confirm(client, session_id, body=None):
    return client.post(
        f"/reconciliation/{session_id}/confirm-matching-config",
        json=(body or _VALID_CONFIG),
    )


# ---------------------------------------------------------------------------
# suggest-matching-config
# ---------------------------------------------------------------------------

class TestSuggestMatchingConfig:
    def test_returns_200_in_preprocessed(self, client, session_id):
        _advance_to_preprocessed(client, session_id)
        assert _suggest(client, session_id).status_code == 200

    def test_state_unchanged_after_suggest(self, client, session_id):
        _advance_to_preprocessed(client, session_id)
        _suggest(client, session_id)
        assert rm.get_current_state(session_id) == ReconciliationState.PREPROCESSED

    def test_response_contains_session_id(self, client, session_id):
        _advance_to_preprocessed(client, session_id)
        data = _suggest(client, session_id).json()
        assert data["session_id"] == session_id

    def test_response_state_is_preprocessed(self, client, session_id):
        _advance_to_preprocessed(client, session_id)
        data = _suggest(client, session_id).json()
        assert data["state"] == "preprocessed"

    def test_response_has_deterministic_scenarios(self, client, session_id):
        _advance_to_preprocessed(client, session_id)
        data = _suggest(client, session_id).json()
        assert isinstance(data["deterministic_scenarios"], list)
        assert len(data["deterministic_scenarios"]) >= 1

    def test_response_has_probabilistic_config(self, client, session_id):
        _advance_to_preprocessed(client, session_id)
        data = _suggest(client, session_id).json()
        prob = data["probabilistic"]
        assert isinstance(prob["weights"], dict)
        assert isinstance(prob["threshold"], float)

    def test_response_has_rationale(self, client, session_id):
        _advance_to_preprocessed(client, session_id)
        data = _suggest(client, session_id).json()
        assert "rationale" in data

    def test_409_in_wrong_state(self, client, session_id):
        # initialized — no preprocessing done
        resp = _suggest(client, session_id)
        assert resp.status_code == 409

    def test_404_unknown_session(self, client):
        resp = client.post("/reconciliation/nonexistent-id/suggest-matching-config")
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# confirm-matching-config
# ---------------------------------------------------------------------------

class TestConfirmMatchingConfig:
    def test_returns_200_with_valid_config(self, client, session_id):
        _advance_to_preprocessed(client, session_id)
        assert _confirm(client, session_id).status_code == 200

    def test_state_advances_to_matching_configured(self, client, session_id):
        _advance_to_preprocessed(client, session_id)
        _confirm(client, session_id)
        assert rm.get_current_state(session_id) == ReconciliationState.MATCHING_CONFIGURED

    def test_response_state_is_matching_configured(self, client, session_id):
        _advance_to_preprocessed(client, session_id)
        data = _confirm(client, session_id).json()
        assert data["state"] == "matching_configured"

    def test_response_echoes_session_id(self, client, session_id):
        _advance_to_preprocessed(client, session_id)
        data = _confirm(client, session_id).json()
        assert data["session_id"] == session_id

    def test_snapshot_key_is_preprocessed(self, client, session_id):
        _advance_to_preprocessed(client, session_id)
        data = _confirm(client, session_id).json()
        assert data["snapshot"]["key"] == "preprocessed"

    def test_matching_config_persisted_in_runtime(self, client, session_id):
        _advance_to_preprocessed(client, session_id)
        _confirm(client, session_id)
        runtime = rm.get_runtime(session_id)
        mc = runtime["config"]["matching_config"]
        assert isinstance(mc["deterministic"], list)
        assert isinstance(mc["probabilistic"], dict)

    def test_422_weights_not_summing_to_one(self, client, session_id):
        _advance_to_preprocessed(client, session_id)
        bad = {
            **_VALID_CONFIG,
            "probabilistic": {
                **_VALID_CONFIG["probabilistic"],
                "weights": {"vendor": 0.50, "amount": 0.50, "date": 0.50},  # sum = 1.5
            },
        }
        resp = _confirm(client, session_id, bad)
        assert resp.status_code == 422

    def test_422_threshold_out_of_range(self, client, session_id):
        _advance_to_preprocessed(client, session_id)
        bad = {
            **_VALID_CONFIG,
            "probabilistic": {
                **_VALID_CONFIG["probabilistic"],
                "threshold": 1.5,   # > 1.0
            },
        }
        resp = _confirm(client, session_id, bad)
        assert resp.status_code == 422

    def test_422_scenario_missing_vendor(self, client, session_id):
        _advance_to_preprocessed(client, session_id)
        bad = {
            **_VALID_CONFIG,
            "deterministic": [
                {
                    "scenario_id": 1,
                    "description": "Missing vendor",
                    "match_fields": ["amount", "date"],   # no vendor
                    "date_tolerance_days": None,
                    "confidence_score": 1.0,
                }
            ],
        }
        resp = _confirm(client, session_id, bad)
        assert resp.status_code == 422

    def test_422_scenario_missing_amount(self, client, session_id):
        _advance_to_preprocessed(client, session_id)
        bad = {
            **_VALID_CONFIG,
            "deterministic": [
                {
                    "scenario_id": 1,
                    "description": "Missing amount",
                    "match_fields": ["vendor", "date"],   # no amount
                    "date_tolerance_days": None,
                    "confidence_score": 1.0,
                }
            ],
        }
        resp = _confirm(client, session_id, bad)
        assert resp.status_code == 422

    def test_409_already_in_matching_configured(self, client, session_id):
        _advance_to_preprocessed(client, session_id)
        _confirm(client, session_id)
        resp = _confirm(client, session_id)
        assert resp.status_code == 409
        assert "matching_configured" in resp.json()["detail"].lower()

    def test_409_in_wrong_state(self, client, session_id):
        # initialized — must be in preprocessed
        resp = _confirm(client, session_id)
        assert resp.status_code == 409

    def test_404_unknown_session(self, client):
        resp = client.post(
            "/reconciliation/nonexistent-id/confirm-matching-config",
            json=_VALID_CONFIG,
        )
        assert resp.status_code == 404
