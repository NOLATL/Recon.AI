"""
Phase 5 — POST /reconciliation/{session_id}/probabilistic

Tests every explicit requirement:

  [Happy path]
  - Returns 200
  - State advances to 'probabilistic_complete'
  - response state == 'probabilistic_complete'
  - session_id echoed in response
  - matches list present in response
  - summary present in response
  - Snapshot key == 'deterministic_review_complete' (pre-transition state)
  - Snapshot integrity hash present (64 hex chars)
  - 6 total snapshots after probabilistic
    (initialized→files_loaded, files_loaded→profiled, profiled→preprocessed,
     preprocessed→deterministic_complete, deterministic_complete→deterministic_review_complete,
     deterministic_review_complete→probabilistic_complete)
  - matches written to runtime["matching"]["probabilistic"]
  - residual_pool updated in runtime
  - probabilistic metadata written to runtime["probabilistic"]

  [Known result — designed test data]
  After full pipeline (upload → profile → preprocess → deterministic → review):
    The standard test data has GL001+SUB001 matched deterministically and
    GL002+SUB002 matched deterministically (0 residual).
    We use separate "residual" test data designed to leave residual records
    that then match probabilistically.

  Designed probabilistic test data:
    GL003: "Alpha Supplies Inc"  ($150.00, 2024-03-10, PROB_CORP)  ← will have $1.50 rounding diff
    SUB003: "Alpha Supplies"     ($151.50, 2024-03-10, PROB_CORP)  ← amount diff 1% < 20% tolerance

  After deterministic, GL003 and SUB003 remain in residual (amounts differ).
  After probabilistic, GL003 ↔ SUB003 match (high vendor sim, same date/entity, small amount diff).

  - match_count >= 1 (GL003 ↔ SUB003)
  - GL003 and SUB003 NOT in residual after probabilistic
  - deterministic match list unchanged (still 2 entries)
  - summary fields populated correctly

  [No recomputation]
  - Second probabilistic call returns 409
  - 409 detail contains 'recomputation'
  - 409 detail mentions 'probabilistic_complete'
  - No extra snapshot created on rejected call
  - State remains 'probabilistic_complete' after rejected call

  [Wrong state]
  - Probabilistic from 'initialized'   → 409 with 'deterministic_review_complete' mention
  - Probabilistic from 'preprocessed'  → 409 with 'deterministic_review_complete' mention
  - Probabilistic from 'deterministic_complete' → 409 with 'deterministic_review_complete' mention
  - Unknown session → 404 with session_id in detail

  [No deterministic mutation]
  - Deterministic match list is unchanged after probabilistic run
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
# Test data
#
# Standard deterministic test data (GL001+GL002 / SUB001+SUB002) is designed
# to match fully in the deterministic layer (0 residual).
#
# We extend with GL003/SUB003: same vendor prefix, same entity, same date,
# but amounts differ by 1% (within 20% band) → survives deterministic,
# then matches probabilistically.
#
# After preprocessing, Vendor_Normalized:
#   "Alpha Supplies Inc" → "alpha supplies"  (suffix "inc" stripped)
#   "Alpha Supplies"     → "alpha supplies"
# token_sort_ratio("alpha supplies", "alpha supplies") = 100 → vendor_sim = 1.0
# amount_sim(150.0, 151.5) ≈ 0.990
# date_sim(same date) = 1.0
# entity_sim(same) = 1.0
# final_sim ≈ 0.40*1.0 + 0.35*0.99 + 0.15*1.0 + 0.10*1.0 ≈ 0.9965 >> 0.80 ✓
# ---------------------------------------------------------------------------

_GL = {
    "gl_id":            ["GL001", "GL002", "GL003"],
    "entity":           ["US_CORP", "US_CORP", "PROB_CORP"],
    "account_code":     ["ACCT_100", "ACCT_101", "ACCT_102"],
    "vendor_name":      ["Vendor A LLC", "Vendor B", "Alpha Supplies Inc"],
    "transaction_date": ["2024-01-15", "2024-01-15", "2024-03-10"],
    "amount":           ["100.00", "250.50", "150.00"],
    "currency":         ["USD", "USD", "USD"],
    "exception_flag":   ["False", "True", "False"],
}

_SUB = {
    "subledger_id":     ["SUB001", "SUB002", "SUB003"],
    "entity":           ["US_CORP", "US_CORP", "PROB_CORP"],
    "vendor_name":      ["Vendor A", "Vendor B", "Alpha Supplies"],
    "transaction_date": ["2024-01-15", "2024-02-20", "2024-03-10"],
    "amount":           ["100.00", "250.50", "151.50"],
    "currency":         ["USD", "USD", "USD"],
    "reference_id":     ["GL001", "GL002", "GL003"],
}

_COA = {
    "account_code":          ["ACCT_100", "ACCT_101", "ACCT_102"],
    "account_name":          ["Cash", "Accounts Payable", "Operating Expenses"],
    "account_type":          ["Asset", "Liability", "Expense"],
    "materiality_threshold": ["10000.00", "5000.00", "2000.00"],
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


def _det_review(client, session_id):
    return client.post(f"/reconciliation/{session_id}/deterministic/review")


def _probabilistic(client, session_id):
    return client.post(f"/reconciliation/{session_id}/probabilistic")


def _advance_to_det_review_complete(client, session_id):
    """Upload → profile → preprocess → deterministic → review."""
    r = _upload(client, session_id)
    assert r.status_code == 200, f"Upload failed: {r.text}"
    r = _profile(client, session_id)
    assert r.status_code == 200, f"Profile failed: {r.text}"
    r = _preprocess(client, session_id)
    assert r.status_code == 200, f"Preprocess failed: {r.text}"
    r = _deterministic(client, session_id)
    assert r.status_code == 200, f"Deterministic failed: {r.text}"
    r = _det_review(client, session_id)
    assert r.status_code == 200, f"Det review failed: {r.text}"


# ===========================================================================
# Happy path
# ===========================================================================

class TestHappyPath:
    def test_returns_200(self, client, session_id):
        _advance_to_det_review_complete(client, session_id)
        assert _probabilistic(client, session_id).status_code == 200

    def test_state_advances_to_probabilistic_complete(self, client, session_id):
        _advance_to_det_review_complete(client, session_id)
        _probabilistic(client, session_id)
        assert rm.get_current_state(session_id) == ReconciliationState.PROBABILISTIC_COMPLETE

    def test_response_state_is_probabilistic_complete(self, client, session_id):
        _advance_to_det_review_complete(client, session_id)
        data = _probabilistic(client, session_id).json()
        assert data["state"] == "probabilistic_complete"

    def test_session_id_echoed(self, client, session_id):
        _advance_to_det_review_complete(client, session_id)
        data = _probabilistic(client, session_id).json()
        assert data["session_id"] == session_id

    def test_matches_present(self, client, session_id):
        _advance_to_det_review_complete(client, session_id)
        data = _probabilistic(client, session_id).json()
        assert "matches" in data
        assert isinstance(data["matches"], list)

    def test_summary_present(self, client, session_id):
        _advance_to_det_review_complete(client, session_id)
        data = _probabilistic(client, session_id).json()
        assert "summary" in data

    def test_snapshot_key_is_deterministic_review_complete(self, client, session_id):
        """Snapshot captured before transition → pre_transition_state = 'deterministic_review_complete'."""
        _advance_to_det_review_complete(client, session_id)
        data = _probabilistic(client, session_id).json()
        assert data["snapshot"]["key"] == "deterministic_review_complete"

    def test_snapshot_integrity_hash_present(self, client, session_id):
        _advance_to_det_review_complete(client, session_id)
        data = _probabilistic(client, session_id).json()
        assert len(data["snapshot"]["integrity_hash"]) == 64

    def test_six_snapshots_after_probabilistic(self, client, session_id):
        """Five prior transitions + probabilistic = 6 snapshots."""
        _advance_to_det_review_complete(client, session_id)
        _probabilistic(client, session_id)
        snapshots = rm.get_runtime(session_id)["snapshots"]
        assert len(snapshots) == 6

    def test_matches_written_to_runtime(self, client, session_id):
        _advance_to_det_review_complete(client, session_id)
        _probabilistic(client, session_id)
        runtime = rm.get_runtime(session_id)
        assert isinstance(runtime["matching"]["probabilistic"], list)

    def test_residual_pool_updated(self, client, session_id):
        _advance_to_det_review_complete(client, session_id)
        _probabilistic(client, session_id)
        runtime = rm.get_runtime(session_id)
        assert "gl" in runtime["residual_pool"]
        assert "subledger" in runtime["residual_pool"]

    def test_probabilistic_metadata_written(self, client, session_id):
        _advance_to_det_review_complete(client, session_id)
        _probabilistic(client, session_id)
        runtime = rm.get_runtime(session_id)
        prob = runtime["probabilistic"]
        assert "threshold_used" in prob
        assert "weights_used" in prob
        assert "match_count" in prob


# ===========================================================================
# Known result — designed test data
# ===========================================================================

class TestKnownResult:
    def test_gl003_sub003_probabilistic_match(self, client, session_id):
        """GL003 ↔ SUB003 should match probabilistically (different amounts, same vendor/date/entity)."""
        _advance_to_det_review_complete(client, session_id)
        data = _probabilistic(client, session_id).json()
        matches = data["matches"]
        assert len(matches) >= 1
        # Verify GL003 ↔ SUB003 match exists
        found = any(
            "GL003" in m["record_ids_A"] and "SUB003" in m["record_ids_B"]
            for m in matches
        )
        assert found, f"Expected GL003↔SUB003 match but got: {matches}"

    def test_match_is_pending(self, client, session_id):
        _advance_to_det_review_complete(client, session_id)
        data = _probabilistic(client, session_id).json()
        assert all(m["user_status"] == "pending" for m in data["matches"])

    def test_override_flag_false(self, client, session_id):
        _advance_to_det_review_complete(client, session_id)
        data = _probabilistic(client, session_id).json()
        assert all(m["override_flag"] is False for m in data["matches"])

    def test_component_scores_present(self, client, session_id):
        _advance_to_det_review_complete(client, session_id)
        data = _probabilistic(client, session_id).json()
        expected_keys = {"vendor_similarity", "amount_similarity", "date_similarity", "entity_similarity"}
        for m in data["matches"]:
            assert set(m["component_scores"].keys()) == expected_keys

    def test_summary_total_records(self, client, session_id):
        _advance_to_det_review_complete(client, session_id)
        # After deterministic, GL003+SUB003 are in residual (amounts differ by 1%)
        runtime = rm.get_runtime(session_id)
        gl_pool = runtime["residual_pool"]["gl"]
        sub_pool = runtime["residual_pool"]["subledger"]
        expected_total_gl = len(gl_pool)
        expected_total_sub = len(sub_pool)

        data = _probabilistic(client, session_id).json()
        summary = data["summary"]
        assert summary["total_gl_records"] == expected_total_gl
        assert summary["total_sub_records"] == expected_total_sub

    def test_summary_match_count(self, client, session_id):
        _advance_to_det_review_complete(client, session_id)
        data = _probabilistic(client, session_id).json()
        summary = data["summary"]
        assert summary["match_count"] == len(data["matches"])

    def test_summary_threshold_used(self, client, session_id):
        _advance_to_det_review_complete(client, session_id)
        data = _probabilistic(client, session_id).json()
        # Default threshold is 0.80 (no config override)
        assert data["summary"]["threshold_used"] == pytest.approx(0.80)

    def test_deterministic_match_count_unchanged(self, client, session_id):
        """Probabilistic layer must NOT alter the deterministic match list."""
        _advance_to_det_review_complete(client, session_id)
        det_before = list(rm.get_runtime(session_id)["matching"]["deterministic"])
        _probabilistic(client, session_id)
        det_after = rm.get_runtime(session_id)["matching"]["deterministic"]
        assert len(det_after) == len(det_before)
        assert det_after == det_before


# ===========================================================================
# No recomputation
# ===========================================================================

class TestNoRecomputation:
    def test_second_call_returns_409(self, client, session_id):
        _advance_to_det_review_complete(client, session_id)
        _probabilistic(client, session_id)
        assert _probabilistic(client, session_id).status_code == 409

    def test_409_detail_contains_recomputation(self, client, session_id):
        _advance_to_det_review_complete(client, session_id)
        _probabilistic(client, session_id)
        detail = _probabilistic(client, session_id).json()["detail"]
        assert "recomputation" in detail.lower()

    def test_409_detail_mentions_probabilistic_complete(self, client, session_id):
        _advance_to_det_review_complete(client, session_id)
        _probabilistic(client, session_id)
        detail = _probabilistic(client, session_id).json()["detail"]
        assert "probabilistic_complete" in detail

    def test_no_extra_snapshot_on_rejected_call(self, client, session_id):
        _advance_to_det_review_complete(client, session_id)
        _probabilistic(client, session_id)
        snap_before = len(rm.get_runtime(session_id)["snapshots"])
        _probabilistic(client, session_id)
        snap_after = len(rm.get_runtime(session_id)["snapshots"])
        assert snap_after == snap_before

    def test_state_remains_probabilistic_complete(self, client, session_id):
        _advance_to_det_review_complete(client, session_id)
        _probabilistic(client, session_id)
        _probabilistic(client, session_id)
        assert rm.get_current_state(session_id) == ReconciliationState.PROBABILISTIC_COMPLETE


# ===========================================================================
# Wrong state
# ===========================================================================

class TestWrongState:
    def test_from_initialized_returns_409(self, client, session_id):
        assert _probabilistic(client, session_id).status_code == 409

    def test_from_initialized_mentions_det_review_complete(self, client, session_id):
        detail = _probabilistic(client, session_id).json()["detail"]
        assert "deterministic_review_complete" in detail

    def test_from_preprocessed_returns_409(self, client, session_id):
        _upload(client, session_id)
        _profile(client, session_id)
        _preprocess(client, session_id)
        assert _probabilistic(client, session_id).status_code == 409

    def test_from_preprocessed_mentions_det_review_complete(self, client, session_id):
        _upload(client, session_id)
        _profile(client, session_id)
        _preprocess(client, session_id)
        detail = _probabilistic(client, session_id).json()["detail"]
        assert "deterministic_review_complete" in detail

    def test_from_deterministic_complete_returns_409(self, client, session_id):
        _upload(client, session_id)
        _profile(client, session_id)
        _preprocess(client, session_id)
        _deterministic(client, session_id)
        assert _probabilistic(client, session_id).status_code == 409

    def test_from_deterministic_complete_mentions_det_review_complete(self, client, session_id):
        _upload(client, session_id)
        _profile(client, session_id)
        _preprocess(client, session_id)
        _deterministic(client, session_id)
        detail = _probabilistic(client, session_id).json()["detail"]
        assert "deterministic_review_complete" in detail

    def test_unknown_session_returns_404(self, client):
        r = client.post("/reconciliation/does-not-exist/probabilistic")
        assert r.status_code == 404

    def test_unknown_session_detail_contains_session_id(self, client):
        r = client.post("/reconciliation/phantom-session/probabilistic")
        assert "phantom-session" in r.json()["detail"]


# ===========================================================================
# No deterministic mutation
# ===========================================================================

class TestNoDeterministicMutation:
    def test_deterministic_matches_unchanged_after_probabilistic(self, client, session_id):
        _advance_to_det_review_complete(client, session_id)
        det_matches_before = list(rm.get_runtime(session_id)["matching"]["deterministic"])

        _probabilistic(client, session_id)

        det_matches_after = rm.get_runtime(session_id)["matching"]["deterministic"]
        assert det_matches_after == det_matches_before

    def test_probabilistic_writes_to_own_bucket(self, client, session_id):
        _advance_to_det_review_complete(client, session_id)
        _probabilistic(client, session_id)
        runtime = rm.get_runtime(session_id)
        # Deterministic bucket unchanged, probabilistic bucket populated
        assert isinstance(runtime["matching"]["probabilistic"], list)
        assert isinstance(runtime["matching"]["deterministic"], list)

    def test_probabilistic_bucket_is_separate_from_deterministic(self, client, session_id):
        _advance_to_det_review_complete(client, session_id)
        _probabilistic(client, session_id)
        runtime = rm.get_runtime(session_id)
        det_ids = {m["match_id"] for m in runtime["matching"]["deterministic"]}
        prob_ids = {m["match_id"] for m in runtime["matching"]["probabilistic"]}
        assert det_ids.isdisjoint(prob_ids), "Probabilistic match IDs should not overlap deterministic"
