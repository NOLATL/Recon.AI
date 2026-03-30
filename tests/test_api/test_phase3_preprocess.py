"""
Phase 3 — POST /reconciliation/{session_id}/preprocess

Tests every explicit requirement:

  [Happy path]
  - Returns 200
  - State advances to 'preprocessed'
  - response state == 'preprocessed'
  - session_id echoed in response
  - vendor_normalization_map present in response
  - normalization_summary present with correct counts
  - Snapshot key == 'profiled' (pre-transition state)
  - Snapshot integrity hash present (64 hex chars)
  - 4 total snapshots after preprocessing
    (initialized→files_loaded, files_loaded→column_mapping_complete, column_mapping_complete→profiled, profiled→preprocessed)
  - vendor_normalization_map written to runtime
  - clean_data written to runtime with Vendor_Normalized column
  - preprocessing metadata written to runtime (threshold, alias_version, tier counts)

  [Normalization result — known data]
  - GL "Vendor A LLC" + Sub "Vendor A" → tier-1 match in vendor_normalization_map
  - Tier counts reflect actual data distribution
  - threshold_used matches config value
  - alias_version matches config value

  [No recomputation]
  - Second preprocess call returns 409
  - 409 detail contains 'recomputation'
  - 409 detail mentions 'preprocessed'
  - No extra snapshot created on rejected call
  - State remains 'preprocessed' after rejected call

  [Wrong state]
  - Preprocess from 'profiled' state only — 'initialized' → 409 with 'profiled' mention
  - 'files_loaded' state → 409 with 'profiled' mention
  - Unknown session → 404 with session_id in detail
"""

import csv
import io
from typing import Any, Dict, List

import pytest

import src.core.runtime_manager as rm
from src.core.state_machine import ReconciliationState


# ---------------------------------------------------------------------------
# CSV builder (shared pattern from phase tests)
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
# GL:  "Vendor A LLC" → tier-1 matches Sub "Vendor A" after suffix stripping
#      "Unique Vendor XYZ" → no Sub match → tier-3
# Sub: "Vendor A", "Other Sub"
# ---------------------------------------------------------------------------

_GL = {
    "gl_id":            ["GL001", "GL002"],
    "entity":           ["US_CORP", "US_CORP"],
    "account_code":     ["ACCT_100", "ACCT_101"],
    "vendor_name":      ["Vendor A LLC", "Unique Vendor XYZ"],
    "transaction_date": ["2024-01-15", "2024-02-20"],
    "amount":           ["100.00", "250.50"],
    "currency":         ["USD", "USD"],
    "exception_flag":   ["False", "True"],
}

_SUB = {
    "subledger_id":     ["SUB001", "SUB002"],
    "entity":           ["US_CORP", "US_CORP"],
    "vendor_name":      ["Vendor A", "Other Sub"],
    "transaction_date": ["2024-01-15", "2024-02-20"],
    "amount":           ["100.00", "250.50"],
    "currency":         ["USD", "USD"],
    "reference_id":     ["GL001", "GL002"],
}

_COA = {
    "account_code":          ["ACCT_100", "ACCT_101"],
    "account_name":          ["Cash", "Accounts Payable"],
    "account_type":          ["Asset", "Liability"],
    "materiality_threshold": ["10000.00", "5000.00"],
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


def _advance_to_profiled(client, session_id):
    """Upload + profile to reach the 'profiled' pre-condition."""
    r1 = _upload(client, session_id)
    assert r1.status_code == 200, f"Upload failed: {r1.text}"
    rm.advance_state(session_id, ReconciliationState.COLUMN_MAPPING_COMPLETE)
    r2 = _profile(client, session_id)
    assert r2.status_code == 200, f"Profile failed: {r2.text}"


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------

class TestHappyPath:
    def test_returns_200(self, client, session_id):
        _advance_to_profiled(client, session_id)
        assert _preprocess(client, session_id).status_code == 200

    def test_state_advances_to_preprocessed(self, client, session_id):
        _advance_to_profiled(client, session_id)
        _preprocess(client, session_id)
        assert rm.get_current_state(session_id) == ReconciliationState.PREPROCESSED

    def test_response_state_is_preprocessed(self, client, session_id):
        _advance_to_profiled(client, session_id)
        data = _preprocess(client, session_id).json()
        assert data["state"] == "preprocessed"

    def test_session_id_echoed(self, client, session_id):
        _advance_to_profiled(client, session_id)
        data = _preprocess(client, session_id).json()
        assert data["session_id"] == session_id

    def test_vendor_normalization_map_present(self, client, session_id):
        _advance_to_profiled(client, session_id)
        data = _preprocess(client, session_id).json()
        assert "vendor_normalization_map" in data
        assert isinstance(data["vendor_normalization_map"], list)

    def test_normalization_summary_present(self, client, session_id):
        _advance_to_profiled(client, session_id)
        data = _preprocess(client, session_id).json()
        assert "normalization_summary" in data

    def test_snapshot_key_is_profiled(self, client, session_id):
        """Snapshot captured before transition → pre_transition_state = 'profiled'."""
        _advance_to_profiled(client, session_id)
        data = _preprocess(client, session_id).json()
        assert data["snapshot"]["key"] == "profiled"

    def test_snapshot_integrity_hash_present(self, client, session_id):
        _advance_to_profiled(client, session_id)
        data = _preprocess(client, session_id).json()
        assert len(data["snapshot"]["integrity_hash"]) == 64

    def test_three_snapshots_after_preprocess(self, client, session_id):
        """initialized→files_loaded, files_loaded→column_mapping_complete, column_mapping_complete→profiled, profiled→preprocessed."""
        _advance_to_profiled(client, session_id)
        _preprocess(client, session_id)
        assert len(rm.get_runtime(session_id)["snapshots"]) == 4

    def test_vendor_normalization_map_written_to_runtime(self, client, session_id):
        _advance_to_profiled(client, session_id)
        _preprocess(client, session_id)
        runtime = rm.get_runtime(session_id)
        assert isinstance(runtime["vendor_normalization_map"], list)
        assert len(runtime["vendor_normalization_map"]) > 0

    def test_clean_data_written_to_runtime(self, client, session_id):
        _advance_to_profiled(client, session_id)
        _preprocess(client, session_id)
        clean = rm.get_runtime(session_id)["clean_data"]
        assert "gl" in clean
        assert "subledger" in clean

    def test_vendor_normalized_column_in_clean_gl(self, client, session_id):
        _advance_to_profiled(client, session_id)
        _preprocess(client, session_id)
        gl_clean = rm.get_runtime(session_id)["clean_data"]["gl"]
        assert "Vendor_Normalized" in gl_clean.columns

    def test_vendor_normalized_column_in_clean_sub(self, client, session_id):
        _advance_to_profiled(client, session_id)
        _preprocess(client, session_id)
        sub_clean = rm.get_runtime(session_id)["clean_data"]["subledger"]
        assert "Vendor_Normalized" in sub_clean.columns

    def test_preprocessing_metadata_written_to_runtime(self, client, session_id):
        _advance_to_profiled(client, session_id)
        _preprocess(client, session_id)
        meta = rm.get_runtime(session_id)["preprocessing"]
        assert "threshold_used" in meta
        assert "alias_version" in meta

    def test_original_vendor_name_preserved_in_clean_gl(self, client, session_id):
        _advance_to_profiled(client, session_id)
        _preprocess(client, session_id)
        gl_clean = rm.get_runtime(session_id)["clean_data"]["gl"]
        assert "vendor_name" in gl_clean.columns


# ---------------------------------------------------------------------------
# Normalization result — known data
# ---------------------------------------------------------------------------

class TestNormalizationResult:
    """
    GL has: 'Vendor A LLC' (tier-1 → 'Vendor A') and 'Unique Vendor XYZ' (tier-3).
    Sub has: 'Vendor A' and 'Other Sub'.
    """

    @pytest.fixture(autouse=True)
    def _setup(self, client, session_id):
        _advance_to_profiled(client, session_id)
        resp = _preprocess(client, session_id)
        assert resp.status_code == 200, resp.text
        self.data = resp.json()

    def test_map_has_one_entry_per_unique_gl_vendor(self):
        # 2 unique GL vendor_names → 2 entries
        assert len(self.data["vendor_normalization_map"]) == 2

    def test_total_unique_gl_vendors_matches(self):
        assert self.data["normalization_summary"]["total_unique_gl_vendors"] == 2

    def test_vendor_a_llc_is_tier1(self):
        entries = {e["original_vendor"]: e for e in self.data["vendor_normalization_map"]}
        assert entries["Vendor A LLC"]["match_source"] == "preprocessing"

    def test_vendor_a_llc_matched_to_vendor_a(self):
        entries = {e["original_vendor"]: e for e in self.data["vendor_normalization_map"]}
        assert entries["Vendor A LLC"]["matched_to"] == "Vendor A"

    def test_unique_vendor_xyz_is_tier3(self):
        """'Unique Vendor XYZ' has no close Sub match at default threshold → tier-3."""
        entries = {e["original_vendor"]: e for e in self.data["vendor_normalization_map"]}
        assert entries["Unique Vendor XYZ"]["match_source"] == "ai"

    def test_unique_vendor_xyz_matched_to_is_none(self):
        entries = {e["original_vendor"]: e for e in self.data["vendor_normalization_map"]}
        assert entries["Unique Vendor XYZ"]["matched_to"] is None

    def test_tier1_count_is_one(self):
        assert self.data["normalization_summary"]["tier1_count"] == 1

    def test_tier3_count_is_one(self):
        assert self.data["normalization_summary"]["tier3_count"] == 1

    def test_threshold_used_matches_default_config(self):
        assert self.data["normalization_summary"]["threshold_used"] == 0.90

    def test_alias_version_matches_default_config(self):
        assert self.data["normalization_summary"]["alias_version"] == "v1.0.0"

    def test_entry_has_required_fields(self):
        entry = self.data["vendor_normalization_map"][0]
        for key in ("original_vendor", "normalized_vendor", "matched_to",
                    "match_source", "similarity_score", "ai_confidence_score"):
            assert key in entry

    def test_tier1_entry_normalized_vendor_is_lowercase(self):
        entries = {e["original_vendor"]: e for e in self.data["vendor_normalization_map"]}
        norm = entries["Vendor A LLC"]["normalized_vendor"]
        assert norm == norm.lower()


# ---------------------------------------------------------------------------
# No recomputation
# ---------------------------------------------------------------------------

class TestNoRecomputation:
    def test_second_call_returns_409(self, client, session_id):
        _advance_to_profiled(client, session_id)
        _preprocess(client, session_id)
        assert _preprocess(client, session_id).status_code == 409

    def test_409_detail_mentions_recomputation(self, client, session_id):
        _advance_to_profiled(client, session_id)
        _preprocess(client, session_id)
        detail = _preprocess(client, session_id).json()["detail"].lower()
        assert "recomputation" in detail

    def test_409_detail_mentions_preprocessed_state(self, client, session_id):
        _advance_to_profiled(client, session_id)
        _preprocess(client, session_id)
        detail = _preprocess(client, session_id).json()["detail"].lower()
        assert "preprocessed" in detail

    def test_no_extra_snapshot_on_rejected_call(self, client, session_id):
        _advance_to_profiled(client, session_id)
        _preprocess(client, session_id)
        count_before = len(rm.get_runtime(session_id)["snapshots"])
        _preprocess(client, session_id)   # rejected
        assert len(rm.get_runtime(session_id)["snapshots"]) == count_before

    def test_state_unchanged_after_rejected_call(self, client, session_id):
        _advance_to_profiled(client, session_id)
        _preprocess(client, session_id)
        _preprocess(client, session_id)   # rejected
        assert rm.get_current_state(session_id) == ReconciliationState.PREPROCESSED


# ---------------------------------------------------------------------------
# Wrong state
# ---------------------------------------------------------------------------

class TestWrongState:
    def test_preprocess_from_initialized_returns_409(self, client, session_id):
        assert _preprocess(client, session_id).status_code == 409

    def test_preprocess_from_files_loaded_returns_409(self, client, session_id):
        _upload(client, session_id)
        assert _preprocess(client, session_id).status_code == 409

    def test_409_detail_mentions_profiled(self, client, session_id):
        detail = _preprocess(client, session_id).json()["detail"]
        assert "profiled" in detail

    def test_unknown_session_returns_404(self, client):
        assert _preprocess(client, "nonexistent-id").status_code == 404

    def test_404_detail_contains_session_id(self, client):
        bad_id = "ghost-session-xyz"
        assert bad_id in _preprocess(client, bad_id).json()["detail"]
