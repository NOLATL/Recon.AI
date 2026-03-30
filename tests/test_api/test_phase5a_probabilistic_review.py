"""
Phase 5A — POST /reconciliation/{session_id}/probabilistic/review

Tests every explicit requirement:

  [Happy path]
  - Returns 200
  - State advances to 'probabilistic_review_complete'
  - response state == 'probabilistic_review_complete'
  - session_id echoed in response
  - accepted_count present in response
  - rejected_count present in response
  - Snapshot key == 'probabilistic_complete' (pre-transition state)
  - Snapshot integrity hash present (64 hex chars)
  - 9 total snapshots after probabilistic review

  [Accept decision]
  - Accepted match: user_status changes to "accepted" in probabilistic bucket
  - Accepted match remains in runtime["matching"]["probabilistic"]
  - Accepted match records NOT returned to residual pool

  [Reject decision]
  - Rejected match: user_status changes to "rejected"
  - Rejected match moves to runtime["matching"]["rejected"]
  - Rejected match removed from runtime["matching"]["probabilistic"]
  - Rejected GL record_ids_A reappear in residual_pool["gl"]
  - Rejected Sub record_ids_B reappear in residual_pool["subledger"]

  [Partial decisions]
  - Matches with no decision remain in probabilistic with user_status="pending"
  - Empty decisions list → all matches stay pending; state still advances

  [No re-review]
  - Second review call returns 409
  - 409 detail contains 'already confirmed' or 'already reviewed'
  - 409 detail mentions 'probabilistic_review_complete'
  - No extra snapshot created on rejected call
  - State remains 'probabilistic_review_complete' after rejected call

  [No recomputation triggered]
  - Deterministic match list unchanged
  - No new matching output produced during review

  [Wrong state]
  - Review from 'initialized'    → 409 with 'probabilistic_complete' mention
  - Review from 'preprocessed'   → 409 with 'probabilistic_complete' mention
  - Review from 'deterministic_review_complete' → 409 with 'probabilistic_complete' mention
  - Unknown session              → 404 with session_id in detail

  [Bad input]
  - Unknown match_id in decisions → 422
"""

import csv
import io
from typing import Any, Dict, List

import pytest

import src.core.runtime_manager as rm
from src.core.state_machine import ReconciliationState


# ---------------------------------------------------------------------------
# CSV builder (shared)
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
# Test data — same 3-record set from Phase 5 tests.
#
# After deterministic: GL001↔SUB001 and GL002↔SUB002 matched. 0 residual.
# After probabilistic: GL003↔SUB003 matched (~99% similarity). 1 prob match.
#
# GL003: "Alpha Supplies Inc" ($150.00, 2024-03-10, PROB_CORP)
# SUB003: "Alpha Supplies"     ($151.50, 2024-03-10, PROB_CORP)
# Amounts differ by $1.50 (~1%) → pass 20% tolerance → probabilistic match.
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


def _prob_review(client, session_id, decisions: list):
    return client.post(
        f"/reconciliation/{session_id}/probabilistic/review",
        json={"decisions": decisions},
    )


def _advance_to_probabilistic_complete(client, session_id):
    """Run the full pipeline to PROBABILISTIC_COMPLETE."""
    r = _upload(client, session_id)
    assert r.status_code == 200, f"upload failed: {r.text}"
    rm.advance_state(session_id, ReconciliationState.COLUMN_MAPPING_COMPLETE)
    for step, fn in [
        ("profile",     lambda: _profile(client, session_id)),
        ("preprocess",  lambda: _preprocess(client, session_id)),
    ]:
        r = fn()
        assert r.status_code == 200, f"{step} failed: {r.text}"
    rm.advance_state(session_id, ReconciliationState.MATCHING_CONFIGURED)
    for step, fn in [
        ("deterministic", lambda: _deterministic(client, session_id)),
        ("det_review",  lambda: _det_review(client, session_id)),
        ("probabilistic", lambda: _probabilistic(client, session_id)),
    ]:
        r = fn()
        assert r.status_code == 200, f"{step} failed: {r.text}"


def _get_prob_match_ids(session_id) -> List[str]:
    """Return all match_ids currently in runtime["matching"]["probabilistic"]."""
    return [m["match_id"] for m in rm.get_runtime(session_id)["matching"]["probabilistic"]]


# ===========================================================================
# Happy path
# ===========================================================================

class TestHappyPath:
    def test_returns_200_accept_all(self, client, session_id):
        _advance_to_probabilistic_complete(client, session_id)
        match_ids = _get_prob_match_ids(session_id)
        decisions = [{"match_id": mid, "decision": "accepted"} for mid in match_ids]
        assert _prob_review(client, session_id, decisions).status_code == 200

    def test_returns_200_empty_decisions(self, client, session_id):
        _advance_to_probabilistic_complete(client, session_id)
        assert _prob_review(client, session_id, []).status_code == 200

    def test_state_advances_to_probabilistic_review_complete(self, client, session_id):
        _advance_to_probabilistic_complete(client, session_id)
        _prob_review(client, session_id, [])
        assert rm.get_current_state(session_id) == ReconciliationState.PROBABILISTIC_REVIEW_COMPLETE

    def test_response_state_is_probabilistic_review_complete(self, client, session_id):
        _advance_to_probabilistic_complete(client, session_id)
        data = _prob_review(client, session_id, []).json()
        assert data["state"] == "probabilistic_review_complete"

    def test_session_id_echoed(self, client, session_id):
        _advance_to_probabilistic_complete(client, session_id)
        data = _prob_review(client, session_id, []).json()
        assert data["session_id"] == session_id

    def test_accepted_count_present(self, client, session_id):
        _advance_to_probabilistic_complete(client, session_id)
        data = _prob_review(client, session_id, []).json()
        assert "accepted_count" in data

    def test_rejected_count_present(self, client, session_id):
        _advance_to_probabilistic_complete(client, session_id)
        data = _prob_review(client, session_id, []).json()
        assert "rejected_count" in data

    def test_snapshot_key_is_probabilistic_complete(self, client, session_id):
        _advance_to_probabilistic_complete(client, session_id)
        data = _prob_review(client, session_id, []).json()
        assert data["snapshot"]["key"] == "probabilistic_complete"

    def test_snapshot_integrity_hash_present(self, client, session_id):
        _advance_to_probabilistic_complete(client, session_id)
        data = _prob_review(client, session_id, []).json()
        assert len(data["snapshot"]["integrity_hash"]) == 64

    def test_seven_snapshots_after_review(self, client, session_id):
        """Eight prior transitions + probabilistic_review = 9 snapshots total."""
        _advance_to_probabilistic_complete(client, session_id)
        _prob_review(client, session_id, [])
        assert len(rm.get_runtime(session_id)["snapshots"]) == 9


# ===========================================================================
# Accept decision
# ===========================================================================

class TestAcceptDecision:
    def test_accepted_count_equals_decisions(self, client, session_id):
        _advance_to_probabilistic_complete(client, session_id)
        match_ids = _get_prob_match_ids(session_id)
        decisions = [{"match_id": mid, "decision": "accepted"} for mid in match_ids]
        data = _prob_review(client, session_id, decisions).json()
        assert data["accepted_count"] == len(match_ids)

    def test_accepted_match_status_updated_in_runtime(self, client, session_id):
        _advance_to_probabilistic_complete(client, session_id)
        match_ids = _get_prob_match_ids(session_id)
        decisions = [{"match_id": mid, "decision": "accepted"} for mid in match_ids]
        _prob_review(client, session_id, decisions)
        prob_list = rm.get_runtime(session_id)["matching"]["probabilistic"]
        assert all(m["user_status"] == "accepted" for m in prob_list)

    def test_accepted_matches_remain_in_probabilistic_bucket(self, client, session_id):
        _advance_to_probabilistic_complete(client, session_id)
        match_ids = _get_prob_match_ids(session_id)
        before_count = len(match_ids)
        decisions = [{"match_id": mid, "decision": "accepted"} for mid in match_ids]
        _prob_review(client, session_id, decisions)
        prob_list = rm.get_runtime(session_id)["matching"]["probabilistic"]
        assert len(prob_list) == before_count

    def test_accepted_records_not_returned_to_residual(self, client, session_id):
        _advance_to_probabilistic_complete(client, session_id)
        match_ids = _get_prob_match_ids(session_id)
        # Get GL IDs of matched records
        prob_matches = rm.get_runtime(session_id)["matching"]["probabilistic"]
        matched_gl_ids = set()
        for m in prob_matches:
            matched_gl_ids.update(m["record_ids_A"])

        decisions = [{"match_id": mid, "decision": "accepted"} for mid in match_ids]
        _prob_review(client, session_id, decisions)

        residual_gl = rm.get_runtime(session_id)["residual_pool"]["gl"]
        if not residual_gl.empty and "gl_id" in residual_gl.columns:
            residual_ids = set(residual_gl["gl_id"].astype(str).tolist())
            assert matched_gl_ids.isdisjoint(residual_ids), \
                "Accepted GL records should NOT be in residual"

    def test_accept_rejected_count_is_zero(self, client, session_id):
        _advance_to_probabilistic_complete(client, session_id)
        match_ids = _get_prob_match_ids(session_id)
        decisions = [{"match_id": mid, "decision": "accepted"} for mid in match_ids]
        data = _prob_review(client, session_id, decisions).json()
        assert data["rejected_count"] == 0


# ===========================================================================
# Reject decision
# ===========================================================================

class TestRejectDecision:
    def test_rejected_count_equals_decisions(self, client, session_id):
        _advance_to_probabilistic_complete(client, session_id)
        match_ids = _get_prob_match_ids(session_id)
        decisions = [{"match_id": mid, "decision": "rejected"} for mid in match_ids]
        data = _prob_review(client, session_id, decisions).json()
        assert data["rejected_count"] == len(match_ids)

    def test_rejected_match_moves_to_rejected_bucket(self, client, session_id):
        _advance_to_probabilistic_complete(client, session_id)
        match_ids = _get_prob_match_ids(session_id)
        decisions = [{"match_id": mid, "decision": "rejected"} for mid in match_ids]
        _prob_review(client, session_id, decisions)
        rejected_list = rm.get_runtime(session_id)["matching"]["rejected"]
        rejected_ids = {m["match_id"] for m in rejected_list}
        for mid in match_ids:
            assert mid in rejected_ids

    def test_rejected_match_removed_from_probabilistic_bucket(self, client, session_id):
        _advance_to_probabilistic_complete(client, session_id)
        match_ids = _get_prob_match_ids(session_id)
        decisions = [{"match_id": mid, "decision": "rejected"} for mid in match_ids]
        _prob_review(client, session_id, decisions)
        prob_list = rm.get_runtime(session_id)["matching"]["probabilistic"]
        prob_ids = {m["match_id"] for m in prob_list}
        for mid in match_ids:
            assert mid not in prob_ids

    def test_rejected_match_status_is_rejected_in_rejected_bucket(self, client, session_id):
        _advance_to_probabilistic_complete(client, session_id)
        match_ids = _get_prob_match_ids(session_id)
        decisions = [{"match_id": mid, "decision": "rejected"} for mid in match_ids]
        _prob_review(client, session_id, decisions)
        rejected_list = rm.get_runtime(session_id)["matching"]["rejected"]
        for m in rejected_list:
            if m["match_id"] in match_ids:
                assert m["user_status"] == "rejected"

    def test_rejected_gl_records_reappear_in_residual_pool(self, client, session_id):
        _advance_to_probabilistic_complete(client, session_id)
        prob_matches = rm.get_runtime(session_id)["matching"]["probabilistic"]
        match_ids    = [m["match_id"] for m in prob_matches]
        rejected_gl_ids = set()
        for m in prob_matches:
            rejected_gl_ids.update(m["record_ids_A"])

        decisions = [{"match_id": mid, "decision": "rejected"} for mid in match_ids]
        _prob_review(client, session_id, decisions)

        residual_gl = rm.get_runtime(session_id)["residual_pool"]["gl"]
        assert not residual_gl.empty, "Residual GL must not be empty after rejection"
        residual_ids = set(residual_gl["gl_id"].astype(str).tolist())
        for gl_id in rejected_gl_ids:
            assert gl_id in residual_ids, f"GL {gl_id} should be in residual after rejection"

    def test_rejected_sub_records_reappear_in_residual_pool(self, client, session_id):
        _advance_to_probabilistic_complete(client, session_id)
        prob_matches = rm.get_runtime(session_id)["matching"]["probabilistic"]
        match_ids    = [m["match_id"] for m in prob_matches]
        rejected_sub_ids = set()
        for m in prob_matches:
            rejected_sub_ids.update(m["record_ids_B"])

        decisions = [{"match_id": mid, "decision": "rejected"} for mid in match_ids]
        _prob_review(client, session_id, decisions)

        residual_sub = rm.get_runtime(session_id)["residual_pool"]["subledger"]
        assert not residual_sub.empty, "Residual Sub must not be empty after rejection"
        residual_ids = set(residual_sub["subledger_id"].astype(str).tolist())
        for sub_id in rejected_sub_ids:
            assert sub_id in residual_ids, f"Sub {sub_id} should be in residual after rejection"

    def test_reject_accepted_count_is_zero(self, client, session_id):
        _advance_to_probabilistic_complete(client, session_id)
        match_ids = _get_prob_match_ids(session_id)
        decisions = [{"match_id": mid, "decision": "rejected"} for mid in match_ids]
        data = _prob_review(client, session_id, decisions).json()
        assert data["accepted_count"] == 0


# ===========================================================================
# Partial decisions
# ===========================================================================

class TestPartialDecisions:
    def test_empty_decisions_all_remain_pending(self, client, session_id):
        _advance_to_probabilistic_complete(client, session_id)
        before_count = len(_get_prob_match_ids(session_id))
        _prob_review(client, session_id, [])
        prob_list = rm.get_runtime(session_id)["matching"]["probabilistic"]
        assert len(prob_list) == before_count
        assert all(m["user_status"] == "pending" for m in prob_list)

    def test_empty_decisions_accepted_rejected_both_zero(self, client, session_id):
        _advance_to_probabilistic_complete(client, session_id)
        data = _prob_review(client, session_id, []).json()
        assert data["accepted_count"] == 0
        assert data["rejected_count"] == 0

    def test_mixed_decisions_counts_correct(self, client, session_id):
        _advance_to_probabilistic_complete(client, session_id)
        match_ids = _get_prob_match_ids(session_id)
        if len(match_ids) < 1:
            pytest.skip("Need at least 1 probabilistic match for this test")
        # Accept the first, skip the rest
        decisions = [{"match_id": match_ids[0], "decision": "accepted"}]
        data = _prob_review(client, session_id, decisions).json()
        assert data["accepted_count"] == 1
        assert data["rejected_count"] == 0

    def test_undecided_matches_remain_pending_in_probabilistic(self, client, session_id):
        _advance_to_probabilistic_complete(client, session_id)
        match_ids = _get_prob_match_ids(session_id)
        if len(match_ids) < 2:
            pytest.skip("Need at least 2 probabilistic matches for this test")
        # Only decide on first match; leave the rest undecided
        decisions = [{"match_id": match_ids[0], "decision": "accepted"}]
        _prob_review(client, session_id, decisions)
        prob_list = rm.get_runtime(session_id)["matching"]["probabilistic"]
        pending = [m for m in prob_list if m["match_id"] in match_ids[1:]]
        assert all(m["user_status"] == "pending" for m in pending)


# ===========================================================================
# No re-review
# ===========================================================================

class TestNoReReview:
    def test_second_review_returns_409(self, client, session_id):
        _advance_to_probabilistic_complete(client, session_id)
        _prob_review(client, session_id, [])
        assert _prob_review(client, session_id, []).status_code == 409

    def test_409_detail_mentions_already_reviewed(self, client, session_id):
        _advance_to_probabilistic_complete(client, session_id)
        _prob_review(client, session_id, [])
        detail = _prob_review(client, session_id, []).json()["detail"]
        assert "already" in detail.lower()

    def test_409_detail_mentions_probabilistic_review_complete(self, client, session_id):
        _advance_to_probabilistic_complete(client, session_id)
        _prob_review(client, session_id, [])
        detail = _prob_review(client, session_id, []).json()["detail"]
        assert "probabilistic_review_complete" in detail

    def test_no_extra_snapshot_on_rejected_call(self, client, session_id):
        _advance_to_probabilistic_complete(client, session_id)
        _prob_review(client, session_id, [])
        snap_before = len(rm.get_runtime(session_id)["snapshots"])
        _prob_review(client, session_id, [])
        snap_after = len(rm.get_runtime(session_id)["snapshots"])
        assert snap_after == snap_before

    def test_state_remains_probabilistic_review_complete(self, client, session_id):
        _advance_to_probabilistic_complete(client, session_id)
        _prob_review(client, session_id, [])
        _prob_review(client, session_id, [])
        assert rm.get_current_state(session_id) == ReconciliationState.PROBABILISTIC_REVIEW_COMPLETE


# ===========================================================================
# No recomputation triggered
# ===========================================================================

class TestNoRecomputation:
    def test_deterministic_matches_unchanged(self, client, session_id):
        _advance_to_probabilistic_complete(client, session_id)
        det_before = list(rm.get_runtime(session_id)["matching"]["deterministic"])
        match_ids = _get_prob_match_ids(session_id)
        decisions = [{"match_id": mid, "decision": "accepted"} for mid in match_ids]
        _prob_review(client, session_id, decisions)
        det_after = rm.get_runtime(session_id)["matching"]["deterministic"]
        assert det_after == det_before

    def test_no_new_probabilistic_matches_created(self, client, session_id):
        """Review must not run the matching algorithm again."""
        _advance_to_probabilistic_complete(client, session_id)
        count_before = len(_get_prob_match_ids(session_id))
        match_ids = _get_prob_match_ids(session_id)
        decisions = [{"match_id": mid, "decision": "accepted"} for mid in match_ids]
        _prob_review(client, session_id, decisions)
        # After accepting all, count should equal before (no new matches added)
        prob_list = rm.get_runtime(session_id)["matching"]["probabilistic"]
        assert len(prob_list) == count_before


# ===========================================================================
# Wrong state
# ===========================================================================

class TestWrongState:
    def test_from_initialized_returns_409(self, client, session_id):
        assert _prob_review(client, session_id, []).status_code == 409

    def test_from_initialized_mentions_probabilistic_complete(self, client, session_id):
        detail = _prob_review(client, session_id, []).json()["detail"]
        assert "probabilistic_complete" in detail

    def test_from_preprocessed_returns_409(self, client, session_id):
        _upload(client, session_id)
        _profile(client, session_id)
        _preprocess(client, session_id)
        assert _prob_review(client, session_id, []).status_code == 409

    def test_from_preprocessed_mentions_probabilistic_complete(self, client, session_id):
        _upload(client, session_id)
        _profile(client, session_id)
        _preprocess(client, session_id)
        detail = _prob_review(client, session_id, []).json()["detail"]
        assert "probabilistic_complete" in detail

    def test_from_det_review_complete_returns_409(self, client, session_id):
        _upload(client, session_id)
        _profile(client, session_id)
        _preprocess(client, session_id)
        _deterministic(client, session_id)
        _det_review(client, session_id)
        assert _prob_review(client, session_id, []).status_code == 409

    def test_from_det_review_complete_mentions_probabilistic_complete(self, client, session_id):
        _upload(client, session_id)
        _profile(client, session_id)
        _preprocess(client, session_id)
        _deterministic(client, session_id)
        _det_review(client, session_id)
        detail = _prob_review(client, session_id, []).json()["detail"]
        assert "probabilistic_complete" in detail

    def test_unknown_session_returns_404(self, client):
        r = client.post(
            "/reconciliation/does-not-exist/probabilistic/review",
            json={"decisions": []},
        )
        assert r.status_code == 404

    def test_unknown_session_detail_contains_session_id(self, client):
        r = client.post(
            "/reconciliation/phantom-session/probabilistic/review",
            json={"decisions": []},
        )
        assert "phantom-session" in r.json()["detail"]


# ===========================================================================
# Bad input
# ===========================================================================

class TestBadInput:
    def test_unknown_match_id_returns_422(self, client, session_id):
        _advance_to_probabilistic_complete(client, session_id)
        decisions = [{"match_id": "does-not-exist", "decision": "accepted"}]
        assert _prob_review(client, session_id, decisions).status_code == 422

    def test_unknown_match_id_detail_mentions_match_id(self, client, session_id):
        _advance_to_probabilistic_complete(client, session_id)
        decisions = [{"match_id": "phantom-id", "decision": "accepted"}]
        detail = _prob_review(client, session_id, decisions).json()["detail"]
        assert "phantom-id" in detail

    def test_invalid_decision_value_returns_422(self, client, session_id):
        _advance_to_probabilistic_complete(client, session_id)
        match_ids = _get_prob_match_ids(session_id)
        if not match_ids:
            pytest.skip("Need probabilistic matches for this test")
        # "approved" is not a valid Literal value
        decisions = [{"match_id": match_ids[0], "decision": "approved"}]
        assert _prob_review(client, session_id, decisions).status_code == 422
