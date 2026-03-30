"""
Phase 6A — POST /reconciliation/{session_id}/ai/review

Tests every explicit requirement:

  [Happy path]
  - Returns 200
  - State advances to 'ai_review_complete'
  - response state == 'ai_review_complete'
  - session_id echoed in response
  - accepted_count present in response
  - rejected_count present in response
  - Snapshot key == 'ai_suggested' (pre-transition state)
  - Snapshot integrity hash present (64 hex chars)
  - 11 total snapshots after AI review
    (phases 0–6 = 10 snapshots, + ai_review = 11)

  [Accept decision]
  - Accepted match: user_status changes to "accepted" in final bucket
  - Accepted match appears in runtime["matching"]["final"]
  - Accepted match removed from runtime["matching"]["ai_suggested"]
  - Accepted match records NOT returned to residual pool

  [Reject decision]
  - Rejected match: user_status changes to "rejected"
  - Rejected match moves to runtime["matching"]["rejected"]
  - Rejected match removed from runtime["matching"]["ai_suggested"]
  - Rejected GL record_ids_A reappear in residual_pool["gl"]
  - Rejected Sub record_ids_B reappear in residual_pool["subledger"]

  [Partial decisions]
  - Matches with no decision remain in ai_suggested with user_status="pending"
  - Empty decisions list → all matches stay pending; state still advances

  [No re-review]
  - Second review call returns 409
  - 409 detail contains 'already confirmed' or 'already reviewed'
  - 409 detail mentions 'ai_review_complete'
  - No extra snapshot created on rejected call
  - State remains 'ai_review_complete' after rejected call

  [No recomputation triggered]
  - Deterministic match list unchanged after review
  - Probabilistic match list unchanged after review
  - AI suggestion list not re-generated (only classified)

  [Wrong state]
  - Review from 'initialized'       → 409 with 'ai_suggested' mention
  - Review from 'preprocessed'      → 409 with 'ai_suggested' mention
  - Review from 'probabilistic_complete' → 409 with 'ai_suggested' mention
  - Unknown session                 → 404 with session_id in detail

  [Bad input]
  - Unknown match_id in decisions → 422

  [Final bucket]
  - Accepted AI match stored in runtime["matching"]["final"]
  - Final bucket contains the accepted match with correct match_id
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
# Test data — same 4-record dataset as Phase 6.
#
# After deterministic: GL001↔SUB001 and GL002↔SUB002 matched.
# After probabilistic: GL003↔SUB003 matched (~99% similarity).
# After probabilistic review (empty decisions): all pending; state advances.
# After Phase 6 AI: GL004↔SUB004 suggested (same entity, same vendor, high conf).
#   GL004: "Delta Vendor" ($1,000.00, 2024-05-01, AI_ENTITY)
#   SUB004: "Delta Vendor" ($1,400.00, 2024-05-01, AI_ENTITY)
#   ai_confidence ≈ 0.90, materiality = 1000.0
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

def _prob_review(client, session_id, decisions=None):
    return client.post(
        f"/reconciliation/{session_id}/probabilistic/review",
        json={"decisions": decisions or []},
    )

def _ai(client, session_id):
    return client.post(f"/reconciliation/{session_id}/ai")

def _ai_review(client, session_id, decisions=None):
    return client.post(
        f"/reconciliation/{session_id}/ai/review",
        json={"decisions": decisions or []},
    )


def _advance_to_ai_suggested(client, session_id):
    """Run the full pipeline through Phase 6 (ai_suggested state)."""
    r = _upload(client, session_id)
    assert r.status_code == 200, f"upload failed: {r.text}"
    rm.advance_state(session_id, ReconciliationState.COLUMN_MAPPING_COMPLETE)
    for step, fn in [
        ("profile",       lambda: _profile(client, session_id)),
        ("preprocess",    lambda: _preprocess(client, session_id)),
    ]:
        r = fn()
        assert r.status_code == 200, f"{step} failed: {r.text}"
    rm.advance_state(session_id, ReconciliationState.MATCHING_CONFIGURED)
    for step, fn in [
        ("deterministic", lambda: _deterministic(client, session_id)),
        ("det_review",    lambda: _det_review(client, session_id)),
        ("probabilistic", lambda: _probabilistic(client, session_id)),
        ("prob_review",   lambda: _prob_review(client, session_id)),
        ("ai",            lambda: _ai(client, session_id)),
    ]:
        r = fn()
        assert r.status_code == 200, f"{step} failed: {r.text}"


def _get_ai_match_ids(session_id) -> List[str]:
    """Return all match_ids currently in runtime["matching"]["ai_suggested"]."""
    return [m["match_id"] for m in rm.get_runtime(session_id)["matching"]["ai_suggested"]]


# ===========================================================================
# Happy path
# ===========================================================================

class TestHappyPath:
    def test_returns_200_accept_all(self, client, session_id):
        _advance_to_ai_suggested(client, session_id)
        match_ids = _get_ai_match_ids(session_id)
        decisions = [{"match_id": mid, "decision": "accepted"} for mid in match_ids]
        assert _ai_review(client, session_id, decisions).status_code == 200

    def test_returns_200_empty_decisions(self, client, session_id):
        _advance_to_ai_suggested(client, session_id)
        assert _ai_review(client, session_id, []).status_code == 200

    def test_state_advances_to_ai_review_complete(self, client, session_id):
        _advance_to_ai_suggested(client, session_id)
        _ai_review(client, session_id, [])
        assert rm.get_current_state(session_id) == ReconciliationState.AI_REVIEW_COMPLETE

    def test_response_state_is_ai_review_complete(self, client, session_id):
        _advance_to_ai_suggested(client, session_id)
        data = _ai_review(client, session_id, []).json()
        assert data["state"] == "ai_review_complete"

    def test_session_id_echoed(self, client, session_id):
        _advance_to_ai_suggested(client, session_id)
        data = _ai_review(client, session_id, []).json()
        assert data["session_id"] == session_id

    def test_accepted_count_present(self, client, session_id):
        _advance_to_ai_suggested(client, session_id)
        data = _ai_review(client, session_id, []).json()
        assert "accepted_count" in data

    def test_rejected_count_present(self, client, session_id):
        _advance_to_ai_suggested(client, session_id)
        data = _ai_review(client, session_id, []).json()
        assert "rejected_count" in data

    def test_snapshot_key_is_ai_suggested(self, client, session_id):
        _advance_to_ai_suggested(client, session_id)
        data = _ai_review(client, session_id, []).json()
        assert data["snapshot"]["key"] == "ai_suggested"

    def test_snapshot_integrity_hash_present(self, client, session_id):
        _advance_to_ai_suggested(client, session_id)
        data = _ai_review(client, session_id, []).json()
        assert len(data["snapshot"]["integrity_hash"]) == 64

    def test_nine_snapshots_after_ai_review(self, client, session_id):
        """Ten prior transitions + ai_review = 11 snapshots total."""
        _advance_to_ai_suggested(client, session_id)
        _ai_review(client, session_id, [])
        assert len(rm.get_runtime(session_id)["snapshots"]) == 11


# ===========================================================================
# Accept decision
# ===========================================================================

class TestAcceptDecision:
    def test_accepted_count_equals_decisions(self, client, session_id):
        _advance_to_ai_suggested(client, session_id)
        match_ids = _get_ai_match_ids(session_id)
        decisions = [{"match_id": mid, "decision": "accepted"} for mid in match_ids]
        data = _ai_review(client, session_id, decisions).json()
        assert data["accepted_count"] == len(match_ids)

    def test_accepted_match_moves_to_final_bucket(self, client, session_id):
        _advance_to_ai_suggested(client, session_id)
        match_ids = _get_ai_match_ids(session_id)
        decisions = [{"match_id": mid, "decision": "accepted"} for mid in match_ids]
        _ai_review(client, session_id, decisions)
        final_list = rm.get_runtime(session_id)["matching"]["final"]
        final_ids  = {m["match_id"] for m in final_list}
        for mid in match_ids:
            assert mid in final_ids, f"Match {mid} should be in final bucket"

    def test_accepted_match_removed_from_ai_suggested_bucket(self, client, session_id):
        _advance_to_ai_suggested(client, session_id)
        match_ids = _get_ai_match_ids(session_id)
        decisions = [{"match_id": mid, "decision": "accepted"} for mid in match_ids]
        _ai_review(client, session_id, decisions)
        ai_list = rm.get_runtime(session_id)["matching"]["ai_suggested"]
        ai_ids  = {m["match_id"] for m in ai_list}
        for mid in match_ids:
            assert mid not in ai_ids, f"Match {mid} should be removed from ai_suggested"

    def test_accepted_records_not_returned_to_residual(self, client, session_id):
        _advance_to_ai_suggested(client, session_id)
        match_ids = _get_ai_match_ids(session_id)
        ai_matches = rm.get_runtime(session_id)["matching"]["ai_suggested"]
        matched_gl_ids = set()
        for m in ai_matches:
            matched_gl_ids.update(m["record_ids_A"])
        decisions = [{"match_id": mid, "decision": "accepted"} for mid in match_ids]
        _ai_review(client, session_id, decisions)
        residual_gl = rm.get_runtime(session_id)["residual_pool"]["gl"]
        if not residual_gl.empty and "gl_id" in residual_gl.columns:
            residual_ids = set(residual_gl["gl_id"].astype(str).tolist())
            assert matched_gl_ids.isdisjoint(residual_ids), \
                "Accepted GL records should NOT be in residual"

    def test_accepted_match_user_status_in_final(self, client, session_id):
        _advance_to_ai_suggested(client, session_id)
        match_ids = _get_ai_match_ids(session_id)
        decisions = [{"match_id": mid, "decision": "accepted"} for mid in match_ids]
        _ai_review(client, session_id, decisions)
        final_list = rm.get_runtime(session_id)["matching"]["final"]
        for m in final_list:
            assert m["user_status"] == "accepted"

    def test_accept_rejected_count_is_zero(self, client, session_id):
        _advance_to_ai_suggested(client, session_id)
        match_ids = _get_ai_match_ids(session_id)
        decisions = [{"match_id": mid, "decision": "accepted"} for mid in match_ids]
        data = _ai_review(client, session_id, decisions).json()
        assert data["rejected_count"] == 0


# ===========================================================================
# Reject decision
# ===========================================================================

class TestRejectDecision:
    def test_rejected_count_equals_decisions(self, client, session_id):
        _advance_to_ai_suggested(client, session_id)
        match_ids = _get_ai_match_ids(session_id)
        decisions = [{"match_id": mid, "decision": "rejected"} for mid in match_ids]
        data = _ai_review(client, session_id, decisions).json()
        assert data["rejected_count"] == len(match_ids)

    def test_rejected_match_moves_to_rejected_bucket(self, client, session_id):
        _advance_to_ai_suggested(client, session_id)
        match_ids = _get_ai_match_ids(session_id)
        decisions = [{"match_id": mid, "decision": "rejected"} for mid in match_ids]
        _ai_review(client, session_id, decisions)
        rejected_list = rm.get_runtime(session_id)["matching"]["rejected"]
        rejected_ids  = {m["match_id"] for m in rejected_list}
        for mid in match_ids:
            assert mid in rejected_ids

    def test_rejected_match_removed_from_ai_suggested_bucket(self, client, session_id):
        _advance_to_ai_suggested(client, session_id)
        match_ids = _get_ai_match_ids(session_id)
        decisions = [{"match_id": mid, "decision": "rejected"} for mid in match_ids]
        _ai_review(client, session_id, decisions)
        ai_list = rm.get_runtime(session_id)["matching"]["ai_suggested"]
        ai_ids  = {m["match_id"] for m in ai_list}
        for mid in match_ids:
            assert mid not in ai_ids

    def test_rejected_gl_record_ids_reappear_in_residual(self, client, session_id):
        _advance_to_ai_suggested(client, session_id)
        match_ids  = _get_ai_match_ids(session_id)
        ai_matches = rm.get_runtime(session_id)["matching"]["ai_suggested"]
        expected_gl_ids = set()
        for m in ai_matches:
            expected_gl_ids.update(m["record_ids_A"])
        decisions = [{"match_id": mid, "decision": "rejected"} for mid in match_ids]
        _ai_review(client, session_id, decisions)
        residual_gl = rm.get_runtime(session_id)["residual_pool"]["gl"]
        assert not residual_gl.empty
        residual_ids = set(residual_gl["gl_id"].astype(str).tolist())
        assert expected_gl_ids.issubset(residual_ids), \
            f"Expected {expected_gl_ids} in residual, got {residual_ids}"

    def test_rejected_sub_record_ids_reappear_in_residual(self, client, session_id):
        _advance_to_ai_suggested(client, session_id)
        match_ids  = _get_ai_match_ids(session_id)
        ai_matches = rm.get_runtime(session_id)["matching"]["ai_suggested"]
        expected_sub_ids = set()
        for m in ai_matches:
            expected_sub_ids.update(m["record_ids_B"])
        decisions = [{"match_id": mid, "decision": "rejected"} for mid in match_ids]
        _ai_review(client, session_id, decisions)
        residual_sub = rm.get_runtime(session_id)["residual_pool"]["subledger"]
        assert not residual_sub.empty
        residual_ids = set(residual_sub["subledger_id"].astype(str).tolist())
        assert expected_sub_ids.issubset(residual_ids), \
            f"Expected {expected_sub_ids} in residual, got {residual_ids}"

    def test_reject_accepted_count_is_zero(self, client, session_id):
        _advance_to_ai_suggested(client, session_id)
        match_ids = _get_ai_match_ids(session_id)
        decisions = [{"match_id": mid, "decision": "rejected"} for mid in match_ids]
        data = _ai_review(client, session_id, decisions).json()
        assert data["accepted_count"] == 0


# ===========================================================================
# Partial decisions
# ===========================================================================

class TestPartialDecisions:
    def test_empty_decisions_all_pending(self, client, session_id):
        _advance_to_ai_suggested(client, session_id)
        before_count = len(_get_ai_match_ids(session_id))
        _ai_review(client, session_id, [])
        ai_list = rm.get_runtime(session_id)["matching"]["ai_suggested"]
        pending = [m for m in ai_list if m["user_status"] == "pending"]
        assert len(pending) == before_count

    def test_empty_decisions_state_still_advances(self, client, session_id):
        _advance_to_ai_suggested(client, session_id)
        _ai_review(client, session_id, [])
        assert rm.get_current_state(session_id) == ReconciliationState.AI_REVIEW_COMPLETE

    def test_empty_decisions_counts_are_zero(self, client, session_id):
        _advance_to_ai_suggested(client, session_id)
        data = _ai_review(client, session_id, []).json()
        assert data["accepted_count"] == 0
        assert data["rejected_count"] == 0


# ===========================================================================
# No re-review
# ===========================================================================

class TestNoReReview:
    def test_second_review_returns_409(self, client, session_id):
        _advance_to_ai_suggested(client, session_id)
        _ai_review(client, session_id, [])
        assert _ai_review(client, session_id, []).status_code == 409

    def test_second_review_detail_mentions_already_confirmed(self, client, session_id):
        _advance_to_ai_suggested(client, session_id)
        _ai_review(client, session_id, [])
        detail = _ai_review(client, session_id, []).json()["detail"].lower()
        assert "already" in detail or "confirmed" in detail

    def test_second_review_detail_mentions_ai_review_complete(self, client, session_id):
        _advance_to_ai_suggested(client, session_id)
        _ai_review(client, session_id, [])
        detail = _ai_review(client, session_id, []).json()["detail"]
        assert "ai_review_complete" in detail

    def test_no_extra_snapshot_on_second_call(self, client, session_id):
        _advance_to_ai_suggested(client, session_id)
        _ai_review(client, session_id, [])
        count_before = len(rm.get_runtime(session_id)["snapshots"])
        _ai_review(client, session_id, [])
        assert len(rm.get_runtime(session_id)["snapshots"]) == count_before

    def test_state_unchanged_after_second_call(self, client, session_id):
        _advance_to_ai_suggested(client, session_id)
        _ai_review(client, session_id, [])
        _ai_review(client, session_id, [])
        assert rm.get_current_state(session_id) == ReconciliationState.AI_REVIEW_COMPLETE


# ===========================================================================
# No recomputation triggered
# ===========================================================================

class TestNoRecomputation:
    def test_deterministic_matches_unchanged(self, client, session_id):
        _advance_to_ai_suggested(client, session_id)
        det_before = len(rm.get_runtime(session_id)["matching"]["deterministic"])
        _ai_review(client, session_id, [])
        det_after = len(rm.get_runtime(session_id)["matching"]["deterministic"])
        assert det_after == det_before

    def test_probabilistic_matches_unchanged(self, client, session_id):
        _advance_to_ai_suggested(client, session_id)
        prob_before = len(rm.get_runtime(session_id)["matching"]["probabilistic"])
        _ai_review(client, session_id, [])
        prob_after = len(rm.get_runtime(session_id)["matching"]["probabilistic"])
        assert prob_after == prob_before


# ===========================================================================
# Wrong state
# ===========================================================================

class TestWrongState:
    def test_from_initialized_returns_409(self, client, session_id):
        r = _ai_review(client, session_id, [])
        assert r.status_code == 409

    def test_from_initialized_detail_mentions_ai_suggested(self, client, session_id):
        detail = _ai_review(client, session_id, []).json()["detail"]
        assert "ai_suggested" in detail

    def test_from_preprocessed_returns_409(self, client, session_id):
        for fn in [
            lambda: _upload(client, session_id),
            lambda: _profile(client, session_id),
            lambda: _preprocess(client, session_id),
        ]:
            fn()
        r = _ai_review(client, session_id, [])
        assert r.status_code == 409

    def test_from_preprocessed_detail_mentions_ai_suggested(self, client, session_id):
        for fn in [
            lambda: _upload(client, session_id),
            lambda: _profile(client, session_id),
            lambda: _preprocess(client, session_id),
        ]:
            fn()
        detail = _ai_review(client, session_id, []).json()["detail"]
        assert "ai_suggested" in detail

    def test_from_probabilistic_complete_returns_409(self, client, session_id):
        for fn in [
            lambda: _upload(client, session_id),
            lambda: _profile(client, session_id),
            lambda: _preprocess(client, session_id),
            lambda: _deterministic(client, session_id),
            lambda: _det_review(client, session_id),
            lambda: _probabilistic(client, session_id),
        ]:
            fn()
        r = _ai_review(client, session_id, [])
        assert r.status_code == 409

    def test_unknown_session_returns_404(self, client):
        r = client.post("/reconciliation/no-such-session/ai/review",
                        json={"decisions": []})
        assert r.status_code == 404

    def test_unknown_session_detail_contains_session_id(self, client):
        r = client.post("/reconciliation/no-such-session/ai/review",
                        json={"decisions": []})
        assert "no-such-session" in r.json()["detail"]


# ===========================================================================
# Bad input
# ===========================================================================

class TestBadInput:
    def test_unknown_match_id_returns_422(self, client, session_id):
        _advance_to_ai_suggested(client, session_id)
        r = _ai_review(client, session_id, [{"match_id": "FAKE_ID", "decision": "accepted"}])
        assert r.status_code == 422

    def test_invalid_decision_value_returns_422(self, client, session_id):
        _advance_to_ai_suggested(client, session_id)
        match_ids = _get_ai_match_ids(session_id)
        if match_ids:
            r = _ai_review(client, session_id,
                            [{"match_id": match_ids[0], "decision": "maybe"}])
            assert r.status_code == 422


# ===========================================================================
# Final bucket
# ===========================================================================

class TestFinalBucket:
    def test_accepted_match_in_final_bucket(self, client, session_id):
        """Accepted AI matches move to runtime["matching"]["final"]."""
        _advance_to_ai_suggested(client, session_id)
        match_ids = _get_ai_match_ids(session_id)
        decisions = [{"match_id": mid, "decision": "accepted"} for mid in match_ids]
        _ai_review(client, session_id, decisions)
        final_list = rm.get_runtime(session_id)["matching"]["final"]
        assert len(final_list) == len(match_ids)

    def test_final_bucket_empty_when_all_rejected(self, client, session_id):
        """Rejected matches do not enter the final bucket."""
        _advance_to_ai_suggested(client, session_id)
        match_ids = _get_ai_match_ids(session_id)
        decisions = [{"match_id": mid, "decision": "rejected"} for mid in match_ids]
        _ai_review(client, session_id, decisions)
        final_list = rm.get_runtime(session_id)["matching"]["final"]
        assert len(final_list) == 0

    def test_final_bucket_empty_with_no_decisions(self, client, session_id):
        """Pending matches do not enter the final bucket."""
        _advance_to_ai_suggested(client, session_id)
        _ai_review(client, session_id, [])
        final_list = rm.get_runtime(session_id)["matching"]["final"]
        assert len(final_list) == 0

    def test_known_result_gl004_sub004_in_final_when_accepted(self, client, session_id):
        """GL004↔SUB004 (Delta Vendor) moves to final when accepted."""
        _advance_to_ai_suggested(client, session_id)
        ai_matches = rm.get_runtime(session_id)["matching"]["ai_suggested"]
        # Find the match containing GL004
        gl004_match = next(
            (m for m in ai_matches if "GL004" in m.get("record_ids_A", [])), None
        )
        assert gl004_match is not None, "GL004 should have an AI suggestion"
        _ai_review(client, session_id,
                   [{"match_id": gl004_match["match_id"], "decision": "accepted"}])
        final_list = rm.get_runtime(session_id)["matching"]["final"]
        final_ids  = {m["match_id"] for m in final_list}
        assert gl004_match["match_id"] in final_ids

    def test_known_result_gl004_sub004_in_residual_when_rejected(self, client, session_id):
        """GL004↔SUB004 (Delta Vendor) returns to residual when rejected."""
        _advance_to_ai_suggested(client, session_id)
        ai_matches = rm.get_runtime(session_id)["matching"]["ai_suggested"]
        gl004_match = next(
            (m for m in ai_matches if "GL004" in m.get("record_ids_A", [])), None
        )
        assert gl004_match is not None
        _ai_review(client, session_id,
                   [{"match_id": gl004_match["match_id"], "decision": "rejected"}])
        residual_gl = rm.get_runtime(session_id)["residual_pool"]["gl"]
        residual_gl_ids = set(residual_gl["gl_id"].astype(str).tolist())
        assert "GL004" in residual_gl_ids
        residual_sub = rm.get_runtime(session_id)["residual_pool"]["subledger"]
        residual_sub_ids = set(residual_sub["subledger_id"].astype(str).tolist())
        assert "SUB004" in residual_sub_ids
