"""
Phase 6 — POST /reconciliation/{session_id}/ai

Tests every explicit requirement:

  [Happy path]
  - Returns 200
  - State advances to 'ai_suggested'
  - response state == 'ai_suggested'
  - session_id echoed in response
  - suggestions list present in response
  - summary present in response with model_used and prompt_version
  - Snapshot key == 'probabilistic_review_complete' (pre-transition state)
  - Snapshot integrity hash present (64 hex chars)
  - 8 total snapshots after AI phase
  - suggestions written to runtime["matching"]["ai_suggested"]
  - ai_suggested_meta written to runtime

  [Known result — designed test data]
  4-record dataset:
    GL001/SUB001: matched deterministically (scenario 1 — exact match)
    GL002/SUB002: matched deterministically (scenario 3 — amount+entity+date)
    GL003/SUB003: matched probabilistically (1% amount diff, same entity/vendor)
    GL004/SUB004: NOT matched in any prior phase (28% amount diff > 20% tolerance)
      GL004: "Delta Vendor" ($1,000.00, 2024-05-01, AI_ENTITY)
      SUB004: "Delta Vendor" ($1,400.00, 2024-05-01, AI_ENTITY)
    After Phase 5A: GL004 and SUB004 remain in residual
    AI suggests GL004 ↔ SUB004 (same entity, same normalized vendor, high confidence)

  - suggestion_count >= 1
  - GL004 and SUB004 appear in at least one suggestion
  - All suggestions have user_status == "pending"
  - All suggestions have override_flag == False
  - supporting_features keys present
  - reasoning_narrative non-empty
  - model_used in summary matches default stub model
  - materiality for GL004 suggestion == 1000.0

  [Advisory — no dataset mutation]
  - Residual pool is unchanged after AI run
  - Deterministic matches unchanged
  - Probabilistic matches unchanged

  [No recomputation]
  - Second AI call returns 409
  - 409 detail contains 'recomputation'
  - 409 detail mentions 'ai_suggested'
  - No extra snapshot on rejected call
  - State remains 'ai_suggested' after rejected call

  [Wrong state]
  - AI from 'initialized'   → 409 with 'probabilistic_review_complete' mention
  - AI from 'preprocessed'  → 409 with 'probabilistic_review_complete' mention
  - AI from 'probabilistic_complete' → 409 with 'probabilistic_review_complete' mention
  - Unknown session → 404 with session_id in detail

  [Ranking]
  - Suggestions sorted by materiality descending in response
"""

import csv
import io
from typing import Any, Dict, List

import pytest

import src.core.runtime_manager as rm
from src.core.state_machine import ReconciliationState
from src.services.ai_matching_service import DEFAULT_AI_MODEL, DEFAULT_PROMPT_VERSION


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
# Test data — 4 GL + 4 Sub + 4 COA entries.
#
# Phases 1–5A will process:
#   GL001 ↔ SUB001 — scenario 1 deterministic (exact match)
#   GL002 ↔ SUB002 — scenario 3 deterministic (amount + entity + date)
#   GL003 ↔ SUB003 — probabilistic (1.5% amount diff, within 20% tolerance)
#   GL004 / SUB004 — residual after all prior phases:
#     • "Delta Vendor" on GL and Sub → tier-1 normalize: "delta vendor" (both)
#     • Amount diff: |1000-1400|/1400 ≈ 28.6% > 20% → probabilistic blocked
#     • AI stub suggests them: same entity, same vendor_norm, high confidence
#
# All expected flows verified by test data math:
#   amount_sim(1000, 1400) = 1 - 400/1400 = 0.714
#   vendor_sim = 1.0 (identical normalized string)
#   date_sim = 1.0 (same date)
#   ai_confidence = 0.40*1.0 + 0.35*0.714 + 0.15*1.0 + 0.10*1.0 = 0.90
# ---------------------------------------------------------------------------

_GL = {
    "gl_id":            ["GL001", "GL002", "GL003", "GL004"],
    "entity":           ["US_CORP", "US_CORP", "PROB_CORP", "AI_ENTITY"],
    "account_code":     ["ACCT_100", "ACCT_101", "ACCT_102", "ACCT_103"],
    "vendor_name":      ["Vendor A LLC", "Unique Vendor XYZ", "Alpha Supplies Inc", "Delta Vendor"],
    "transaction_date": ["2024-01-15", "2024-02-20", "2024-03-10", "2024-05-01"],
    "amount":           ["100.00", "250.50", "150.00", "1000.00"],
    "currency":         ["USD", "USD", "USD", "USD"],
    "exception_flag":   ["False", "True", "False", "False"],
}

_SUB = {
    "subledger_id":     ["SUB001", "SUB002", "SUB003", "SUB004"],
    "entity":           ["US_CORP", "US_CORP", "PROB_CORP", "AI_ENTITY"],
    "vendor_name":      ["Vendor A", "Other Sub", "Alpha Supplies", "Delta Vendor"],
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


def _advance_to_prob_review_complete(client, session_id):
    """Run the full pipeline through Phase 5A."""
    steps = [
        ("upload",         lambda: _upload(client, session_id)),
        ("profile",        lambda: _profile(client, session_id)),
        ("preprocess",     lambda: _preprocess(client, session_id)),
        ("deterministic",  lambda: _deterministic(client, session_id)),
        ("det_review",     lambda: _det_review(client, session_id)),
        ("probabilistic",  lambda: _probabilistic(client, session_id)),
        ("prob_review",    lambda: _prob_review(client, session_id)),
    ]
    for step, fn in steps:
        r = fn()
        assert r.status_code == 200, f"{step} failed: {r.text}"


# ===========================================================================
# Happy path
# ===========================================================================

class TestHappyPath:
    def test_returns_200(self, client, session_id):
        _advance_to_prob_review_complete(client, session_id)
        assert _ai(client, session_id).status_code == 200

    def test_state_advances_to_ai_suggested(self, client, session_id):
        _advance_to_prob_review_complete(client, session_id)
        _ai(client, session_id)
        assert rm.get_current_state(session_id) == ReconciliationState.AI_SUGGESTED

    def test_response_state_is_ai_suggested(self, client, session_id):
        _advance_to_prob_review_complete(client, session_id)
        data = _ai(client, session_id).json()
        assert data["state"] == "ai_suggested"

    def test_session_id_echoed(self, client, session_id):
        _advance_to_prob_review_complete(client, session_id)
        data = _ai(client, session_id).json()
        assert data["session_id"] == session_id

    def test_suggestions_list_present(self, client, session_id):
        _advance_to_prob_review_complete(client, session_id)
        data = _ai(client, session_id).json()
        assert "suggestions" in data
        assert isinstance(data["suggestions"], list)

    def test_summary_present(self, client, session_id):
        _advance_to_prob_review_complete(client, session_id)
        data = _ai(client, session_id).json()
        assert "summary" in data

    def test_summary_has_model_used(self, client, session_id):
        _advance_to_prob_review_complete(client, session_id)
        data = _ai(client, session_id).json()
        assert "model_used" in data["summary"]

    def test_summary_has_prompt_version(self, client, session_id):
        _advance_to_prob_review_complete(client, session_id)
        data = _ai(client, session_id).json()
        assert "prompt_version" in data["summary"]

    def test_snapshot_key_is_probabilistic_review_complete(self, client, session_id):
        _advance_to_prob_review_complete(client, session_id)
        data = _ai(client, session_id).json()
        assert data["snapshot"]["key"] == "probabilistic_review_complete"

    def test_snapshot_integrity_hash_present(self, client, session_id):
        _advance_to_prob_review_complete(client, session_id)
        data = _ai(client, session_id).json()
        assert len(data["snapshot"]["integrity_hash"]) == 64

    def test_eight_snapshots_after_ai(self, client, session_id):
        """Seven prior transitions + AI = 8 snapshots."""
        _advance_to_prob_review_complete(client, session_id)
        _ai(client, session_id)
        assert len(rm.get_runtime(session_id)["snapshots"]) == 8

    def test_suggestions_written_to_runtime(self, client, session_id):
        _advance_to_prob_review_complete(client, session_id)
        _ai(client, session_id)
        runtime = rm.get_runtime(session_id)
        assert isinstance(runtime["matching"]["ai_suggested"], list)

    def test_ai_meta_written_to_runtime(self, client, session_id):
        _advance_to_prob_review_complete(client, session_id)
        _ai(client, session_id)
        meta = rm.get_runtime(session_id)["ai_suggested_meta"]
        assert "model_used" in meta
        assert "prompt_version" in meta
        assert "suggestion_count" in meta


# ===========================================================================
# Known result — designed test data
# ===========================================================================

class TestKnownResult:
    def test_gl004_sub004_suggested(self, client, session_id):
        """GL004 ↔ SUB004 should appear in AI suggestions."""
        _advance_to_prob_review_complete(client, session_id)
        data = _ai(client, session_id).json()
        found = any(
            "GL004" in s["record_ids_A"] and "SUB004" in s["record_ids_B"]
            for s in data["suggestions"]
        )
        assert found, f"Expected GL004↔SUB004 suggestion, got: {data['suggestions']}"

    def test_suggestion_count_at_least_one(self, client, session_id):
        _advance_to_prob_review_complete(client, session_id)
        data = _ai(client, session_id).json()
        assert len(data["suggestions"]) >= 1

    def test_all_suggestions_pending(self, client, session_id):
        _advance_to_prob_review_complete(client, session_id)
        data = _ai(client, session_id).json()
        assert all(s["user_status"] == "pending" for s in data["suggestions"])

    def test_all_suggestions_override_flag_false(self, client, session_id):
        _advance_to_prob_review_complete(client, session_id)
        data = _ai(client, session_id).json()
        assert all(s["override_flag"] is False for s in data["suggestions"])

    def test_supporting_features_keys(self, client, session_id):
        _advance_to_prob_review_complete(client, session_id)
        data = _ai(client, session_id).json()
        required = {"vendor_similarity", "amount_diff", "amount_diff_pct",
                    "date_diff_days", "entity"}
        for s in data["suggestions"]:
            assert required.issubset(set(s["supporting_features"].keys()))

    def test_reasoning_narrative_non_empty(self, client, session_id):
        _advance_to_prob_review_complete(client, session_id)
        data = _ai(client, session_id).json()
        assert all(len(s["reasoning_narrative"]) > 0 for s in data["suggestions"])

    def test_model_used_is_default_stub(self, client, session_id):
        _advance_to_prob_review_complete(client, session_id)
        data = _ai(client, session_id).json()
        assert data["summary"]["model_used"] == DEFAULT_AI_MODEL

    def test_prompt_version_is_default(self, client, session_id):
        _advance_to_prob_review_complete(client, session_id)
        data = _ai(client, session_id).json()
        assert data["summary"]["prompt_version"] == DEFAULT_PROMPT_VERSION

    def test_gl004_suggestion_materiality(self, client, session_id):
        """GL004 has amount $1,000.00 → materiality == 1000.0."""
        _advance_to_prob_review_complete(client, session_id)
        data = _ai(client, session_id).json()
        gl004_suggestions = [
            s for s in data["suggestions"] if "GL004" in s["record_ids_A"]
        ]
        assert gl004_suggestions, "No suggestion for GL004"
        assert gl004_suggestions[0]["materiality"] == pytest.approx(1000.0)

    def test_suggestion_count_in_summary_matches_list(self, client, session_id):
        _advance_to_prob_review_complete(client, session_id)
        data = _ai(client, session_id).json()
        assert data["summary"]["suggestion_count"] == len(data["suggestions"])


# ===========================================================================
# Advisory — no dataset mutation
# ===========================================================================

class TestAdvisory:
    def test_residual_pool_unchanged_after_ai(self, client, session_id):
        _advance_to_prob_review_complete(client, session_id)
        pool_before_gl  = set(rm.get_runtime(session_id)["residual_pool"]["gl"]["gl_id"].tolist())
        pool_before_sub = set(rm.get_runtime(session_id)["residual_pool"]["subledger"]["subledger_id"].tolist())

        _ai(client, session_id)

        pool_after_gl  = set(rm.get_runtime(session_id)["residual_pool"]["gl"]["gl_id"].tolist())
        pool_after_sub = set(rm.get_runtime(session_id)["residual_pool"]["subledger"]["subledger_id"].tolist())

        assert pool_after_gl  == pool_before_gl,  "Residual GL pool must not change after AI"
        assert pool_after_sub == pool_before_sub, "Residual Sub pool must not change after AI"

    def test_deterministic_matches_unchanged(self, client, session_id):
        _advance_to_prob_review_complete(client, session_id)
        det_before = list(rm.get_runtime(session_id)["matching"]["deterministic"])
        _ai(client, session_id)
        det_after = rm.get_runtime(session_id)["matching"]["deterministic"]
        assert det_after == det_before

    def test_probabilistic_matches_unchanged(self, client, session_id):
        _advance_to_prob_review_complete(client, session_id)
        prob_before = list(rm.get_runtime(session_id)["matching"]["probabilistic"])
        _ai(client, session_id)
        prob_after = rm.get_runtime(session_id)["matching"]["probabilistic"]
        assert prob_after == prob_before


# ===========================================================================
# No recomputation
# ===========================================================================

class TestNoRecomputation:
    def test_second_ai_call_returns_409(self, client, session_id):
        _advance_to_prob_review_complete(client, session_id)
        _ai(client, session_id)
        assert _ai(client, session_id).status_code == 409

    def test_409_detail_contains_recomputation(self, client, session_id):
        _advance_to_prob_review_complete(client, session_id)
        _ai(client, session_id)
        detail = _ai(client, session_id).json()["detail"]
        assert "recomputation" in detail.lower()

    def test_409_detail_mentions_ai_suggested(self, client, session_id):
        _advance_to_prob_review_complete(client, session_id)
        _ai(client, session_id)
        detail = _ai(client, session_id).json()["detail"]
        assert "ai_suggested" in detail

    def test_no_extra_snapshot_on_rejected_call(self, client, session_id):
        _advance_to_prob_review_complete(client, session_id)
        _ai(client, session_id)
        snap_count = len(rm.get_runtime(session_id)["snapshots"])
        _ai(client, session_id)
        assert len(rm.get_runtime(session_id)["snapshots"]) == snap_count

    def test_state_remains_ai_suggested(self, client, session_id):
        _advance_to_prob_review_complete(client, session_id)
        _ai(client, session_id)
        _ai(client, session_id)
        assert rm.get_current_state(session_id) == ReconciliationState.AI_SUGGESTED


# ===========================================================================
# Wrong state
# ===========================================================================

class TestWrongState:
    def test_from_initialized_returns_409(self, client, session_id):
        assert _ai(client, session_id).status_code == 409

    def test_from_initialized_mentions_prob_review_complete(self, client, session_id):
        detail = _ai(client, session_id).json()["detail"]
        assert "probabilistic_review_complete" in detail

    def test_from_preprocessed_returns_409(self, client, session_id):
        _upload(client, session_id)
        _profile(client, session_id)
        _preprocess(client, session_id)
        assert _ai(client, session_id).status_code == 409

    def test_from_probabilistic_complete_returns_409(self, client, session_id):
        _upload(client, session_id)
        _profile(client, session_id)
        _preprocess(client, session_id)
        _deterministic(client, session_id)
        _det_review(client, session_id)
        _probabilistic(client, session_id)
        assert _ai(client, session_id).status_code == 409

    def test_from_probabilistic_complete_mentions_prob_review_complete(self, client, session_id):
        _upload(client, session_id)
        _profile(client, session_id)
        _preprocess(client, session_id)
        _deterministic(client, session_id)
        _det_review(client, session_id)
        _probabilistic(client, session_id)
        detail = _ai(client, session_id).json()["detail"]
        assert "probabilistic_review_complete" in detail

    def test_unknown_session_returns_404(self, client):
        r = client.post("/reconciliation/ghost-session/ai")
        assert r.status_code == 404

    def test_unknown_session_detail_contains_session_id(self, client):
        r = client.post("/reconciliation/ghost-session/ai")
        assert "ghost-session" in r.json()["detail"]


# ===========================================================================
# Ranking
# ===========================================================================

class TestRanking:
    def test_suggestions_sorted_by_materiality_descending(self, client, session_id):
        _advance_to_prob_review_complete(client, session_id)
        data = _ai(client, session_id).json()
        mats = [s["materiality"] for s in data["suggestions"]]
        assert mats == sorted(mats, reverse=True), \
            f"Suggestions not sorted by materiality desc: {mats}"
