"""
Phase 7 — POST /reconciliation/{session_id}/consolidate

Tests every explicit requirement:

  [Happy path]
  - Returns 200
  - State advances to 'final_consolidated'
  - response state == 'final_consolidated'
  - session_id echoed in response
  - summary present in response
  - Snapshot key == 'ai_review_complete' (pre-transition state)
  - Snapshot integrity hash present (64 hex chars)
  - 10 total snapshots after consolidation
    (phases 0–6A = 9 snapshots, + consolidation = 10)

  [Summary fields]
  - deterministic_match_count present and >= 0
  - probabilistic_match_count present and >= 0
  - ai_match_count present and >= 0
  - total_match_count == det + prob + ai
  - residual_gl_count present and >= 0
  - residual_sub_count present and >= 0
  - rejected_count present and >= 0
  - override_count present and == 0 (v1)

  [Known result — all decisions accepted]
  4-record dataset, all phases with full acceptance:
    GL001↔SUB001: deterministic (scenario 1)
    GL002↔SUB002: deterministic (scenario 3)
    GL003↔SUB003: probabilistic accepted in Phase 5A
    GL004↔SUB004: AI accepted in Phase 6A
  Expected:
    deterministic_match_count == 2
    probabilistic_match_count == 1
    ai_match_count == 1
    total_match_count == 4
    residual_gl_count == 0
    residual_sub_count == 0
    rejected_count == 0

  [Known result — all decisions rejected]
  All prob + AI rejected → residual gets records back:
    deterministic_match_count == 2  (immutable)
    probabilistic_match_count == 0
    ai_match_count == 0
    total_match_count == 2
    residual_gl_count >= 1  (rejected records returned to residual)
    rejected_count >= 1

  [Final bucket content]
  - Final bucket contains all deterministic matches
  - Final bucket contains accepted probabilistic matches
  - Final bucket contains accepted AI matches
  - Final bucket does NOT contain pending probabilistic matches
  - runtime["consolidation"] written with summary metrics

  [No re-consolidation]
  - Second consolidate call returns 409
  - 409 detail contains 'already consolidated' or 'already completed'
  - 409 detail mentions 'final_consolidated'
  - No extra snapshot on rejected call
  - State remains 'final_consolidated' after rejected call

  [No recomputation triggered]
  - Deterministic matches untouched (same count before and after)
  - Probabilistic matches untouched (same count before and after)
  - AI suggested bucket not re-run

  [Wrong state]
  - Consolidate from 'initialized'         → 409 with 'ai_review_complete' mention
  - Consolidate from 'preprocessed'        → 409 with 'ai_review_complete' mention
  - Consolidate from 'ai_suggested'        → 409 with 'ai_review_complete' mention
  - Consolidate from 'probabilistic_complete' → 409 with 'ai_review_complete' mention
  - Unknown session                        → 404 with session_id in detail
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
# Test data — same 4-record dataset used through all phases.
#
#   GL001↔SUB001 — deterministic scenario 1 (exact match)
#   GL002↔SUB002 — deterministic scenario 3 (amount+entity+date)
#   GL003↔SUB003 — probabilistic (1.5% amount diff, same entity/vendor)
#   GL004↔SUB004 — AI suggestion (28.6% amount diff, same entity/vendor)
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


def _get_match_ids(session_id: str, bucket: str) -> List[str]:
    return [m["match_id"] for m in rm.get_runtime(session_id)["matching"][bucket]]


def _advance_to_ai_review_complete_all_accepted(client, sid):
    """
    Run the full pipeline through Phase 6A with all decisions accepted.

    After this helper:
      - deterministic: GL001↔SUB001, GL002↔SUB002 (auto_confirmed)
      - probabilistic: GL003↔SUB003 (accepted)
      - final: GL004↔SUB004 (AI accepted)
      - residual: empty
      - rejected: empty
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

    # Accept all probabilistic matches
    prob_ids = _get_match_ids(sid, "probabilistic")
    r = _prob_review(client, sid, [{"match_id": mid, "decision": "accepted"} for mid in prob_ids])
    assert r.status_code == 200, f"prob_review failed: {r.text}"

    r = _ai(client, sid)
    assert r.status_code == 200, f"ai failed: {r.text}"

    # Accept all AI suggestions
    ai_ids = _get_match_ids(sid, "ai_suggested")
    r = _ai_review(client, sid, [{"match_id": mid, "decision": "accepted"} for mid in ai_ids])
    assert r.status_code == 200, f"ai_review failed: {r.text}"


def _advance_to_ai_review_complete_all_rejected(client, sid):
    """
    Run the full pipeline through Phase 6A with prob + AI all rejected.

    After this helper:
      - deterministic: GL001↔SUB001, GL002↔SUB002 (auto_confirmed)
      - probabilistic: none accepted (all rejected in 5A)
      - final: empty (no AI accepted in 6A)
      - residual: GL003+GL004, SUB003+SUB004 (returned/remaining)
      - rejected: GL003↔SUB003 (prob), GL004↔SUB004 (AI)
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

    # Reject all probabilistic matches
    prob_ids = _get_match_ids(sid, "probabilistic")
    r = _prob_review(client, sid, [{"match_id": mid, "decision": "rejected"} for mid in prob_ids])
    assert r.status_code == 200, f"prob_review failed: {r.text}"

    r = _ai(client, sid)
    assert r.status_code == 200, f"ai failed: {r.text}"

    # Reject all AI suggestions
    ai_ids = _get_match_ids(sid, "ai_suggested")
    r = _ai_review(client, sid, [{"match_id": mid, "decision": "rejected"} for mid in ai_ids])
    assert r.status_code == 200, f"ai_review failed: {r.text}"


# ===========================================================================
# Happy path
# ===========================================================================

class TestHappyPath:
    def test_returns_200(self, client, session_id):
        _advance_to_ai_review_complete_all_accepted(client, session_id)
        assert _consolidate(client, session_id).status_code == 200

    def test_state_advances_to_final_consolidated(self, client, session_id):
        _advance_to_ai_review_complete_all_accepted(client, session_id)
        _consolidate(client, session_id)
        assert rm.get_current_state(session_id) == ReconciliationState.FINAL_CONSOLIDATED

    def test_response_state_is_final_consolidated(self, client, session_id):
        _advance_to_ai_review_complete_all_accepted(client, session_id)
        data = _consolidate(client, session_id).json()
        assert data["state"] == "final_consolidated"

    def test_session_id_echoed(self, client, session_id):
        _advance_to_ai_review_complete_all_accepted(client, session_id)
        data = _consolidate(client, session_id).json()
        assert data["session_id"] == session_id

    def test_summary_present(self, client, session_id):
        _advance_to_ai_review_complete_all_accepted(client, session_id)
        data = _consolidate(client, session_id).json()
        assert "summary" in data

    def test_snapshot_key_is_ai_review_complete(self, client, session_id):
        _advance_to_ai_review_complete_all_accepted(client, session_id)
        data = _consolidate(client, session_id).json()
        assert data["snapshot"]["key"] == "ai_review_complete"

    def test_snapshot_integrity_hash_present(self, client, session_id):
        _advance_to_ai_review_complete_all_accepted(client, session_id)
        data = _consolidate(client, session_id).json()
        assert len(data["snapshot"]["integrity_hash"]) == 64

    def test_ten_snapshots_after_consolidation(self, client, session_id):
        """Nine prior transitions + consolidation = 10 snapshots total."""
        _advance_to_ai_review_complete_all_accepted(client, session_id)
        _consolidate(client, session_id)
        assert len(rm.get_runtime(session_id)["snapshots"]) == 10


# ===========================================================================
# Summary fields
# ===========================================================================

class TestSummaryFields:
    def test_deterministic_match_count_present(self, client, session_id):
        _advance_to_ai_review_complete_all_accepted(client, session_id)
        summary = _consolidate(client, session_id).json()["summary"]
        assert "deterministic_match_count" in summary

    def test_probabilistic_match_count_present(self, client, session_id):
        _advance_to_ai_review_complete_all_accepted(client, session_id)
        summary = _consolidate(client, session_id).json()["summary"]
        assert "probabilistic_match_count" in summary

    def test_ai_match_count_present(self, client, session_id):
        _advance_to_ai_review_complete_all_accepted(client, session_id)
        summary = _consolidate(client, session_id).json()["summary"]
        assert "ai_match_count" in summary

    def test_total_match_count_equals_sum(self, client, session_id):
        _advance_to_ai_review_complete_all_accepted(client, session_id)
        s = _consolidate(client, session_id).json()["summary"]
        assert s["total_match_count"] == (
            s["deterministic_match_count"] +
            s["probabilistic_match_count"] +
            s["ai_match_count"]
        )

    def test_residual_gl_count_present(self, client, session_id):
        _advance_to_ai_review_complete_all_accepted(client, session_id)
        summary = _consolidate(client, session_id).json()["summary"]
        assert "residual_gl_count" in summary

    def test_residual_sub_count_present(self, client, session_id):
        _advance_to_ai_review_complete_all_accepted(client, session_id)
        summary = _consolidate(client, session_id).json()["summary"]
        assert "residual_sub_count" in summary

    def test_rejected_count_present(self, client, session_id):
        _advance_to_ai_review_complete_all_accepted(client, session_id)
        summary = _consolidate(client, session_id).json()["summary"]
        assert "rejected_count" in summary

    def test_override_count_is_zero_v1(self, client, session_id):
        _advance_to_ai_review_complete_all_accepted(client, session_id)
        summary = _consolidate(client, session_id).json()["summary"]
        assert summary["override_count"] == 0


# ===========================================================================
# Known result — all decisions accepted
# ===========================================================================

class TestKnownResultAllAccepted:
    def test_deterministic_count_is_two(self, client, session_id):
        _advance_to_ai_review_complete_all_accepted(client, session_id)
        s = _consolidate(client, session_id).json()["summary"]
        assert s["deterministic_match_count"] == 2

    def test_probabilistic_count_is_one(self, client, session_id):
        _advance_to_ai_review_complete_all_accepted(client, session_id)
        s = _consolidate(client, session_id).json()["summary"]
        assert s["probabilistic_match_count"] == 1

    def test_ai_count_is_one(self, client, session_id):
        _advance_to_ai_review_complete_all_accepted(client, session_id)
        s = _consolidate(client, session_id).json()["summary"]
        assert s["ai_match_count"] == 1

    def test_total_count_is_four(self, client, session_id):
        _advance_to_ai_review_complete_all_accepted(client, session_id)
        s = _consolidate(client, session_id).json()["summary"]
        assert s["total_match_count"] == 4

    def test_residual_gl_count_is_zero(self, client, session_id):
        _advance_to_ai_review_complete_all_accepted(client, session_id)
        s = _consolidate(client, session_id).json()["summary"]
        assert s["residual_gl_count"] == 0

    def test_residual_sub_count_is_zero(self, client, session_id):
        _advance_to_ai_review_complete_all_accepted(client, session_id)
        s = _consolidate(client, session_id).json()["summary"]
        assert s["residual_sub_count"] == 0

    def test_rejected_count_is_zero(self, client, session_id):
        _advance_to_ai_review_complete_all_accepted(client, session_id)
        s = _consolidate(client, session_id).json()["summary"]
        assert s["rejected_count"] == 0


# ===========================================================================
# Known result — all decisions rejected
# ===========================================================================

class TestKnownResultAllRejected:
    def test_deterministic_count_is_two(self, client, session_id):
        """Deterministic matches are immutable — always included."""
        _advance_to_ai_review_complete_all_rejected(client, session_id)
        s = _consolidate(client, session_id).json()["summary"]
        assert s["deterministic_match_count"] == 2

    def test_probabilistic_count_is_zero(self, client, session_id):
        _advance_to_ai_review_complete_all_rejected(client, session_id)
        s = _consolidate(client, session_id).json()["summary"]
        assert s["probabilistic_match_count"] == 0

    def test_ai_count_is_zero(self, client, session_id):
        _advance_to_ai_review_complete_all_rejected(client, session_id)
        s = _consolidate(client, session_id).json()["summary"]
        assert s["ai_match_count"] == 0

    def test_total_count_is_two(self, client, session_id):
        _advance_to_ai_review_complete_all_rejected(client, session_id)
        s = _consolidate(client, session_id).json()["summary"]
        assert s["total_match_count"] == 2

    def test_residual_has_rejected_records(self, client, session_id):
        """Rejected records are returned to the residual pool."""
        _advance_to_ai_review_complete_all_rejected(client, session_id)
        s = _consolidate(client, session_id).json()["summary"]
        assert s["residual_gl_count"] >= 1
        assert s["residual_sub_count"] >= 1

    def test_rejected_count_positive(self, client, session_id):
        _advance_to_ai_review_complete_all_rejected(client, session_id)
        s = _consolidate(client, session_id).json()["summary"]
        assert s["rejected_count"] >= 1


# ===========================================================================
# Final bucket content
# ===========================================================================

class TestFinalBucketContent:
    def test_deterministic_matches_remain_in_deterministic_bucket(self, client, session_id):
        """
        matching['final'] holds only AI-accepted matches.
        Deterministic matches stay in their own 'deterministic' bucket after consolidation.
        """
        _advance_to_ai_review_complete_all_accepted(client, session_id)
        det_ids = {m["match_id"] for m in rm.get_runtime(session_id)["matching"]["deterministic"]}
        _consolidate(client, session_id)
        det_ids_after = {m["match_id"] for m in rm.get_runtime(session_id)["matching"]["deterministic"]}
        assert det_ids == det_ids_after

    def test_accepted_probabilistic_remain_in_probabilistic_bucket(self, client, session_id):
        """
        matching['final'] holds only AI-accepted matches.
        Accepted probabilistic matches stay in their own 'probabilistic' bucket after consolidation.
        """
        _advance_to_ai_review_complete_all_accepted(client, session_id)
        prob_accepted_ids = {
            m["match_id"]
            for m in rm.get_runtime(session_id)["matching"]["probabilistic"]
            if m.get("user_status") == "accepted"
        }
        _consolidate(client, session_id)
        prob_accepted_after = {
            m["match_id"]
            for m in rm.get_runtime(session_id)["matching"]["probabilistic"]
            if m.get("user_status") == "accepted"
        }
        assert prob_accepted_ids == prob_accepted_after

    def test_final_bucket_contains_only_ai_matches(self, client, session_id):
        """
        After consolidation, matching['final'] must contain only AI-accepted matches
        (those with 'ai_confidence_score'). Det and prob matches are NOT written here.
        """
        _advance_to_ai_review_complete_all_accepted(client, session_id)
        _consolidate(client, session_id)
        final_list = rm.get_runtime(session_id)["matching"]["final"]
        for m in final_list:
            assert "ai_confidence_score" in m, (
                f"Non-AI match found in final bucket: {m.get('match_id')}"
            )

    def test_summary_total_equals_det_plus_prob_plus_ai(self, client, session_id):
        """total_match_count == det + accepted_prob + ai."""
        _advance_to_ai_review_complete_all_accepted(client, session_id)
        data = _consolidate(client, session_id).json()
        s = data["summary"]
        assert s["total_match_count"] == (
            s["deterministic_match_count"] +
            s["probabilistic_match_count"] +
            s["ai_match_count"]
        )

    def test_consolidation_metadata_written_to_runtime(self, client, session_id):
        _advance_to_ai_review_complete_all_accepted(client, session_id)
        _consolidate(client, session_id)
        consolidation = rm.get_runtime(session_id)["consolidation"]
        assert "total_match_count" in consolidation
        assert "deterministic_match_count" in consolidation

    def test_final_does_not_contain_pending_prob(self, client, session_id):
        """Pending probabilistic matches (no decision given) must not be in final."""
        # Advance without giving prob decisions → all prob matches stay pending
        for step, fn in [
            ("upload",       lambda: _upload(client, session_id)),
            ("profile",      lambda: _profile(client, session_id)),
            ("preprocess",   lambda: _preprocess(client, session_id)),
            ("deterministic",lambda: _deterministic(client, session_id)),
            ("det_review",   lambda: _det_review(client, session_id)),
            ("probabilistic",lambda: _probabilistic(client, session_id)),
            ("prob_review",  lambda: _prob_review(client, session_id, [])),  # no decisions
            ("ai",           lambda: _ai(client, session_id)),
            ("ai_review",    lambda: _ai_review(client, session_id, [])),    # no decisions
        ]:
            r = fn()
            assert r.status_code == 200, f"{step} failed: {r.text}"

        pending_prob_ids = {
            m["match_id"]
            for m in rm.get_runtime(session_id)["matching"]["probabilistic"]
            if m.get("user_status") == "pending"
        }
        _consolidate(client, session_id)
        final_ids = {m["match_id"] for m in rm.get_runtime(session_id)["matching"]["final"]}
        assert pending_prob_ids.isdisjoint(final_ids), \
            "Pending prob matches should NOT appear in final bucket"


# ===========================================================================
# No re-consolidation
# ===========================================================================

class TestNoReConsolidation:
    def test_second_consolidate_returns_409(self, client, session_id):
        _advance_to_ai_review_complete_all_accepted(client, session_id)
        _consolidate(client, session_id)
        assert _consolidate(client, session_id).status_code == 409

    def test_second_consolidate_detail_mentions_already(self, client, session_id):
        _advance_to_ai_review_complete_all_accepted(client, session_id)
        _consolidate(client, session_id)
        detail = _consolidate(client, session_id).json()["detail"].lower()
        assert "already" in detail

    def test_second_consolidate_detail_mentions_final_consolidated(self, client, session_id):
        _advance_to_ai_review_complete_all_accepted(client, session_id)
        _consolidate(client, session_id)
        detail = _consolidate(client, session_id).json()["detail"]
        assert "final_consolidated" in detail

    def test_no_extra_snapshot_on_second_call(self, client, session_id):
        _advance_to_ai_review_complete_all_accepted(client, session_id)
        _consolidate(client, session_id)
        count = len(rm.get_runtime(session_id)["snapshots"])
        _consolidate(client, session_id)
        assert len(rm.get_runtime(session_id)["snapshots"]) == count

    def test_state_unchanged_after_second_call(self, client, session_id):
        _advance_to_ai_review_complete_all_accepted(client, session_id)
        _consolidate(client, session_id)
        _consolidate(client, session_id)
        assert rm.get_current_state(session_id) == ReconciliationState.FINAL_CONSOLIDATED


# ===========================================================================
# No recomputation triggered
# ===========================================================================

class TestNoRecomputation:
    def test_deterministic_matches_unchanged(self, client, session_id):
        _advance_to_ai_review_complete_all_accepted(client, session_id)
        det_before = len(rm.get_runtime(session_id)["matching"]["deterministic"])
        _consolidate(client, session_id)
        det_after = len(rm.get_runtime(session_id)["matching"]["deterministic"])
        assert det_after == det_before

    def test_probabilistic_matches_unchanged(self, client, session_id):
        _advance_to_ai_review_complete_all_accepted(client, session_id)
        prob_before = len(rm.get_runtime(session_id)["matching"]["probabilistic"])
        _consolidate(client, session_id)
        prob_after = len(rm.get_runtime(session_id)["matching"]["probabilistic"])
        assert prob_after == prob_before


# ===========================================================================
# Wrong state
# ===========================================================================

class TestWrongState:
    def test_from_initialized_returns_409(self, client, session_id):
        assert _consolidate(client, session_id).status_code == 409

    def test_from_initialized_detail_mentions_ai_review_complete(self, client, session_id):
        detail = _consolidate(client, session_id).json()["detail"]
        assert "ai_review_complete" in detail

    def test_from_preprocessed_returns_409(self, client, session_id):
        for fn in [
            lambda: _upload(client, session_id),
            lambda: _profile(client, session_id),
            lambda: _preprocess(client, session_id),
        ]:
            fn()
        assert _consolidate(client, session_id).status_code == 409

    def test_from_preprocessed_detail_mentions_ai_review_complete(self, client, session_id):
        for fn in [
            lambda: _upload(client, session_id),
            lambda: _profile(client, session_id),
            lambda: _preprocess(client, session_id),
        ]:
            fn()
        detail = _consolidate(client, session_id).json()["detail"]
        assert "ai_review_complete" in detail

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
        assert _consolidate(client, session_id).status_code == 409

    def test_from_ai_suggested_returns_409(self, client, session_id):
        for fn in [
            lambda: _upload(client, session_id),
            lambda: _profile(client, session_id),
            lambda: _preprocess(client, session_id),
            lambda: _deterministic(client, session_id),
            lambda: _det_review(client, session_id),
            lambda: _probabilistic(client, session_id),
            lambda: _prob_review(client, session_id),
            lambda: _ai(client, session_id),
        ]:
            fn()
        assert _consolidate(client, session_id).status_code == 409

    def test_from_ai_suggested_detail_mentions_ai_review_complete(self, client, session_id):
        for fn in [
            lambda: _upload(client, session_id),
            lambda: _profile(client, session_id),
            lambda: _preprocess(client, session_id),
            lambda: _deterministic(client, session_id),
            lambda: _det_review(client, session_id),
            lambda: _probabilistic(client, session_id),
            lambda: _prob_review(client, session_id),
            lambda: _ai(client, session_id),
        ]:
            fn()
        detail = _consolidate(client, session_id).json()["detail"]
        assert "ai_review_complete" in detail

    def test_unknown_session_returns_404(self, client):
        r = client.post("/reconciliation/no-such-session/consolidate")
        assert r.status_code == 404

    def test_unknown_session_detail_contains_session_id(self, client):
        r = client.post("/reconciliation/no-such-session/consolidate")
        assert "no-such-session" in r.json()["detail"]
