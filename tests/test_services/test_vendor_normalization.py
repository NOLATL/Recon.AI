"""
Unit tests for src/services/vendor_normalization.py

Coverage:

  [normalize_vendor — text transformation]
  - Lowercasing
  - Punctuation removal
  - Corporate suffix stripping (single and stacked)
  - Stopword removal
  - Alias map applied before normalization
  - Empty / null input returns empty string
  - Suffix stripping is trailing-only (interior suffixes preserved)

  [Tier 1 — deterministic preprocessing matches]
  - Suffix difference causes tier-1 match (GL "Vendor A LLC" ↔ Sub "Vendor A")
  - Case difference causes tier-1 match
  - Punctuation difference causes tier-1 match
  - Stopword difference causes tier-1 match
  - Alias map resolves to tier-1 match
  - match_source == "preprocessing", similarity_score is None

  [Tier 2 — NLP fuzzy matches]
  - Vendor with high NLP similarity and low threshold resolves to tier-2
  - match_source == "nlp", similarity_score is a float in 0.0–1.0
  - matched_to is the original Sub vendor string
  - Vendor that doesn't exceed threshold falls through to tier-3

  [Threshold boundary]
  - threshold=0.0  → any non-tier-1 vendor with a Sub candidate lands in tier-2
  - threshold=1.0  → near-identical-but-not-exact strings fall to tier-3
  - Raising threshold reduces tier-2 count and increases tier-3 count

  [Tier 3 — AI residual stub]
  - Vendor with no Sub candidates → tier-3
  - Vendor below threshold → tier-3
  - match_source == "ai", similarity_score is None, ai_confidence_score is None
  - matched_to is None

  [Vendor_Normalized column]
  - Both GL and Subledger DataFrames gain a "Vendor_Normalized" column
  - Tier-1 matched vendors share the same Vendor_Normalized value in GL and Sub
  - Tier-2 matched vendors share the same Vendor_Normalized value in GL and Sub
  - Tier-3 vendors in GL get their own normalized form
  - Original vendor_name column is preserved unchanged
  - Null vendor_name maps to None in Vendor_Normalized

  [Edge cases]
  - GL vendor_name column absent → ValueError
  - Sub vendor_name column absent → ValueError
  - Empty DataFrames (zero rows) → returns empty entries list, columns added
  - Multiple GL vendors mapped correctly (no cross-contamination)
"""

import pandas as pd
import pytest

from src.services.vendor_normalization import normalize_vendor, run_normalization


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _gl(vendors: list, amounts: list | None = None) -> pd.DataFrame:
    """Build a minimal GL DataFrame with vendor_name + amount."""
    n = len(vendors)
    return pd.DataFrame({
        "gl_id":            [f"GL{i:03}" for i in range(n)],
        "vendor_name":      vendors,
        "amount":           amounts if amounts else [100.0] * n,
        "transaction_date": ["2024-01-01"] * n,
    })


def _sub(vendors: list) -> pd.DataFrame:
    """Build a minimal Subledger DataFrame with vendor_name."""
    n = len(vendors)
    return pd.DataFrame({
        "subledger_id": [f"SUB{i:03}" for i in range(n)],
        "vendor_name":  vendors,
        "amount":       [100.0] * n,
    })


# ---------------------------------------------------------------------------
# normalize_vendor — text transformation
# ---------------------------------------------------------------------------

class TestNormalizeVendor:
    def test_lowercasing(self):
        assert normalize_vendor("VENDOR A", {}) == "vendor a"

    def test_punctuation_removed(self):
        assert normalize_vendor("Vendor-A, Inc.", {}) == "vendor a"

    def test_single_corporate_suffix_stripped(self):
        assert normalize_vendor("Vendor A LLC", {}) == "vendor a"

    def test_multiple_stacked_suffixes_stripped(self):
        # "Corp Ltd" → both trailing suffixes removed
        assert normalize_vendor("Vendor A Corp Ltd", {}) == "vendor a"

    def test_interior_suffix_not_stripped(self):
        # "Corp" in the middle should NOT be removed
        result = normalize_vendor("Corp Vendor A", {})
        assert "corp" in result   # "corp" stays because it's not trailing

    def test_stopword_removed(self):
        assert normalize_vendor("The Vendor A", {}) == "vendor a"

    def test_multiple_stopwords_removed(self):
        assert normalize_vendor("The Vendor of A", {}) == "vendor a"

    def test_alias_applied_before_normalization(self):
        alias = {"Acme Alias": "Acme Corporation"}
        # "Acme Corporation" → normalize → "acme" (corporation stripped)
        assert normalize_vendor("Acme Alias", alias) == "acme"

    def test_alias_does_not_apply_to_unregistered_name(self):
        alias = {"Known Alias": "Canonical Corp"}
        # No alias match → plain normalization
        assert normalize_vendor("Unknown Corp", alias) == "unknown"

    def test_empty_string_returns_empty(self):
        assert normalize_vendor("", {}) == ""

    def test_whitespace_only_returns_empty(self):
        assert normalize_vendor("   ", {}) == ""

    def test_fully_stopword_vendor_returns_empty(self):
        # "The and of" → all stopwords → empty after removal
        assert normalize_vendor("The and of", {}) == ""

    def test_fully_suffix_vendor_returns_empty(self):
        # "LLC Ltd" → both stripped → empty
        assert normalize_vendor("LLC Ltd", {}) == ""

    def test_unicode_normalized(self):
        # café → café (NFC, lowercase)
        result = normalize_vendor("Café Corp", {})
        assert "caf" in result   # the é may differ in repr but won't crash


# ---------------------------------------------------------------------------
# Tier 1 — deterministic preprocessing matches
# ---------------------------------------------------------------------------

class TestTier1:
    def test_suffix_difference_resolves_tier1(self):
        """'Vendor A LLC' (GL) and 'Vendor A' (Sub) both normalize to 'vendor a'."""
        gl  = _gl(["Vendor A LLC"])
        sub = _sub(["Vendor A"])
        result = run_normalization(gl, sub)
        assert len(result.entries) == 1
        entry = result.entries[0]
        assert entry.match_source == "preprocessing"
        assert entry.original_vendor == "Vendor A LLC"
        assert entry.matched_to == "Vendor A"

    def test_case_difference_resolves_tier1(self):
        gl  = _gl(["VENDOR B"])
        sub = _sub(["vendor b"])
        result = run_normalization(gl, sub)
        assert result.entries[0].match_source == "preprocessing"

    def test_punctuation_difference_resolves_tier1(self):
        gl  = _gl(["Vendor-C, Inc."])
        sub = _sub(["Vendor C"])
        result = run_normalization(gl, sub)
        assert result.entries[0].match_source == "preprocessing"

    def test_stopword_difference_resolves_tier1(self):
        gl  = _gl(["The Vendor D"])
        sub = _sub(["Vendor D"])
        result = run_normalization(gl, sub)
        assert result.entries[0].match_source == "preprocessing"

    def test_alias_map_resolves_tier1(self):
        """Alias 'Acme Alias' → 'Acme Corp' → normalizes to 'acme' to match Sub."""
        gl    = _gl(["Acme Alias"])
        sub   = _sub(["Acme Corp"])
        alias = {"Acme Alias": "Acme Corp"}
        result = run_normalization(gl, sub, alias_map=alias)
        assert result.entries[0].match_source == "preprocessing"
        assert result.entries[0].matched_to == "Acme Corp"

    def test_tier1_similarity_score_is_none(self):
        gl  = _gl(["Vendor A LLC"])
        sub = _sub(["Vendor A"])
        result = run_normalization(gl, sub)
        assert result.entries[0].similarity_score is None

    def test_tier1_ai_confidence_is_none(self):
        gl  = _gl(["Vendor A LLC"])
        sub = _sub(["Vendor A"])
        result = run_normalization(gl, sub)
        assert result.entries[0].ai_confidence_score is None

    def test_tier1_count_reflects_matched_count(self):
        gl  = _gl(["Vendor A LLC", "Vendor B Corp"])
        sub = _sub(["Vendor A", "Vendor B"])
        result = run_normalization(gl, sub)
        assert result.tier1_count == 2
        assert result.tier2_count == 0
        assert result.tier3_count == 0


# ---------------------------------------------------------------------------
# Tier 2 — NLP fuzzy matches
# ---------------------------------------------------------------------------

class TestTier2:
    """
    Use a lenient threshold (0.70) so that obviously similar-but-non-identical
    strings resolve via tier 2 without depending on exact RapidFuzz scores.

    Pair: "Smithfield Corp" (GL) vs "Smithfeeld Corp" (Sub)
      - GL normalized:  "smithfield"   (Corp stripped)
      - Sub normalized: "smithfeeld"   (Corp stripped)
      - Differ by 1 char → high similarity but not identical → tier-1 miss
    """

    _GL_VENDOR  = "Smithfield Corp"
    _SUB_VENDOR = "Smithfeeld Corp"
    _THRESHOLD  = 0.70   # lenient — reliable tier-2 match

    @pytest.fixture()
    def tier2_result(self):
        gl  = _gl([self._GL_VENDOR])
        sub = _sub([self._SUB_VENDOR])
        return run_normalization(gl, sub, nlp_threshold=self._THRESHOLD)

    def test_match_source_is_nlp(self, tier2_result):
        assert tier2_result.entries[0].match_source == "nlp"

    def test_similarity_score_is_float(self, tier2_result):
        score = tier2_result.entries[0].similarity_score
        assert isinstance(score, float)

    def test_similarity_score_in_range(self, tier2_result):
        score = tier2_result.entries[0].similarity_score
        assert 0.0 <= score <= 1.0

    def test_similarity_score_above_threshold(self, tier2_result):
        score = tier2_result.entries[0].similarity_score
        assert score >= self._THRESHOLD

    def test_matched_to_is_original_sub_vendor(self, tier2_result):
        assert tier2_result.entries[0].matched_to == self._SUB_VENDOR

    def test_original_vendor_preserved(self, tier2_result):
        assert tier2_result.entries[0].original_vendor == self._GL_VENDOR

    def test_tier2_count_is_one(self, tier2_result):
        assert tier2_result.tier2_count == 1
        assert tier2_result.tier1_count == 0
        assert tier2_result.tier3_count == 0


# ---------------------------------------------------------------------------
# Threshold boundary
# ---------------------------------------------------------------------------

class TestThresholdBoundary:
    """
    Use "Smithfield" vs "Smithfeeld" (1-char difference, high similarity).

    threshold=0.70 → tier-2 (similarity high enough)
    threshold=1.0  → tier-3 (similarity < 100%, can't pass score_cutoff=100)
    """

    _GL_VENDOR  = "Smithfield"
    _SUB_VENDOR = "Smithfeeld"

    def _run(self, threshold: float):
        return run_normalization(
            _gl([self._GL_VENDOR]),
            _sub([self._SUB_VENDOR]),
            nlp_threshold=threshold,
        )

    def test_low_threshold_gives_tier2(self):
        result = self._run(0.70)
        assert result.entries[0].match_source == "nlp"

    def test_full_threshold_gives_tier3(self):
        """threshold=1.0 means score_cutoff=100; near-identical strings won't reach 100."""
        result = self._run(1.0)
        assert result.entries[0].match_source == "ai"

    def test_raising_threshold_from_low_to_high_changes_tier(self):
        low  = self._run(0.70)
        high = self._run(1.0)
        assert low.tier2_count  > high.tier2_count
        assert low.tier3_count  < high.tier3_count

    def test_threshold_zero_resolves_similar_vendor_to_tier2(self):
        """threshold=0.0 → score_cutoff=0; any similarity is accepted."""
        result = self._run(0.0)
        # These strings are similar, so they should match at threshold=0.0
        assert result.entries[0].match_source in ("preprocessing", "nlp")

    def test_threshold_stored_in_result(self):
        result = self._run(0.85)
        assert result.threshold_used == 0.85


# ---------------------------------------------------------------------------
# Tier 3 — AI residual stub
# ---------------------------------------------------------------------------

class TestTier3:
    def test_no_sub_vendors_forces_tier3(self):
        """With an empty Subledger, no match is possible → all vendors go to tier-3."""
        gl  = _gl(["Alpha Dynamics"])
        sub = _sub([])
        result = run_normalization(gl, sub)
        assert result.entries[0].match_source == "ai"

    def test_completely_dissimilar_vendor_is_tier3(self):
        """'Alpha Dynamics' vs 'Omega Services' — very low similarity → tier-3 at 0.90."""
        gl  = _gl(["Alpha Dynamics"])
        sub = _sub(["Omega Services"])
        result = run_normalization(gl, sub, nlp_threshold=0.90)
        assert result.entries[0].match_source == "ai"

    def test_tier3_similarity_score_is_none(self):
        gl  = _gl(["Alpha Dynamics"])
        sub = _sub([])
        result = run_normalization(gl, sub)
        assert result.entries[0].similarity_score is None

    def test_tier3_ai_confidence_is_zero_or_none_when_no_key(self):
        gl  = _gl(["Alpha Dynamics"])
        sub = _sub([])
        result = run_normalization(gl, sub)
        # Without OPENAI_API_KEY the AI client is skipped; confidence is 0.0 (no match)
        assert result.entries[0].ai_confidence_score in (None, 0.0)

    def test_tier3_matched_to_is_none(self):
        gl  = _gl(["Alpha Dynamics"])
        sub = _sub([])
        result = run_normalization(gl, sub)
        assert result.entries[0].matched_to is None

    def test_tier3_count_reflects_unresolved(self):
        gl  = _gl(["A", "B", "C"])
        sub = _sub([])   # empty subledger → all tier-3
        result = run_normalization(gl, sub)
        assert result.tier3_count == 3
        assert result.tier1_count == 0
        assert result.tier2_count == 0


# ---------------------------------------------------------------------------
# Vendor_Normalized column correctness
# ---------------------------------------------------------------------------

class TestVendorNormalizedColumn:
    def test_gl_gains_vendor_normalized_column(self):
        result = run_normalization(_gl(["Vendor A LLC"]), _sub(["Vendor A"]))
        assert "Vendor_Normalized" in result.gl_df.columns

    def test_sub_gains_vendor_normalized_column(self):
        result = run_normalization(_gl(["Vendor A LLC"]), _sub(["Vendor A"]))
        assert "Vendor_Normalized" in result.sub_df.columns

    def test_original_vendor_name_preserved_in_gl(self):
        result = run_normalization(_gl(["Vendor A LLC"]), _sub(["Vendor A"]))
        assert result.gl_df["vendor_name"].iloc[0] == "Vendor A LLC"

    def test_original_vendor_name_preserved_in_sub(self):
        result = run_normalization(_gl(["Vendor A LLC"]), _sub(["Vendor A"]))
        assert result.sub_df["vendor_name"].iloc[0] == "Vendor A"

    def test_tier1_gl_and_sub_share_vendor_normalized(self):
        """
        'Vendor A LLC' (GL) matches 'Vendor A' (Sub) via tier-1.
        Both should get the same Vendor_Normalized so they can be joined downstream.
        """
        result = run_normalization(_gl(["Vendor A LLC"]), _sub(["Vendor A"]))
        gl_norm  = result.gl_df["Vendor_Normalized"].iloc[0]
        sub_norm = result.sub_df["Vendor_Normalized"].iloc[0]
        assert gl_norm == sub_norm

    def test_tier2_gl_and_sub_share_vendor_normalized(self):
        """
        'Smithfield Corp' (GL) matches 'Smithfeeld Corp' (Sub) via tier-2.
        Both should get the same Vendor_Normalized.
        """
        result = run_normalization(
            _gl(["Smithfield Corp"]),
            _sub(["Smithfeeld Corp"]),
            nlp_threshold=0.70,
        )
        gl_norm  = result.gl_df["Vendor_Normalized"].iloc[0]
        sub_norm = result.sub_df["Vendor_Normalized"].iloc[0]
        assert gl_norm == sub_norm

    def test_tier3_vendor_normalized_is_gl_normalized_form(self):
        """Tier-3 vendors get their own normalized text as Vendor_Normalized."""
        result = run_normalization(_gl(["Alpha Dynamics LLC"]), _sub([]))
        # "Alpha Dynamics LLC" → strip "LLC" → "alpha dynamics"
        assert result.gl_df["Vendor_Normalized"].iloc[0] == "alpha dynamics"

    def test_null_vendor_name_maps_to_none(self):
        gl  = _gl([None])
        sub = _sub(["Vendor A"])
        result = run_normalization(gl, sub)
        assert pd.isna(result.gl_df["Vendor_Normalized"].iloc[0])

    def test_multiple_vendors_no_cross_contamination(self):
        """Each GL vendor gets its own Vendor_Normalized, not another vendor's."""
        gl  = _gl(["Vendor A LLC", "Vendor B Corp"])
        sub = _sub(["Vendor A", "Vendor B"])
        result = run_normalization(gl, sub)
        norms = result.gl_df["Vendor_Normalized"].tolist()
        assert norms[0] != norms[1]


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------

class TestEdgeCases:
    def test_missing_gl_vendor_name_column_raises(self):
        gl  = pd.DataFrame({"amount": [100.0]})
        sub = _sub(["Vendor A"])
        with pytest.raises(ValueError, match="vendor_name"):
            run_normalization(gl, sub)

    def test_missing_sub_vendor_name_column_raises(self):
        gl  = _gl(["Vendor A"])
        sub = pd.DataFrame({"amount": [100.0]})
        with pytest.raises(ValueError, match="vendor_name"):
            run_normalization(gl, sub)

    def test_empty_gl_returns_empty_entries(self):
        gl  = _gl([])
        sub = _sub(["Vendor A"])
        result = run_normalization(gl, sub)
        assert result.entries == []
        assert result.tier1_count == 0

    def test_empty_gl_vendor_normalized_column_added(self):
        result = run_normalization(_gl([]), _sub(["Vendor A"]))
        assert "Vendor_Normalized" in result.gl_df.columns

    def test_alias_version_stored_in_result(self):
        result = run_normalization(_gl(["V"]), _sub(["V"]), alias_version="v2.3.1")
        assert result.alias_version == "v2.3.1"

    def test_default_alias_version(self):
        result = run_normalization(_gl(["V"]), _sub(["V"]))
        assert result.alias_version == "v1.0.0"

    def test_to_map_list_returns_correct_length(self):
        gl  = _gl(["A", "B", "C"])
        sub = _sub(["A", "B"])
        result = run_normalization(gl, sub)
        assert len(result.to_map_list()) == 3

    def test_to_map_list_entry_has_required_keys(self):
        result = run_normalization(_gl(["Vendor A LLC"]), _sub(["Vendor A"]))
        keys = result.to_map_list()[0].keys()
        for expected in ("original_vendor", "normalized_vendor", "matched_to",
                         "match_source", "similarity_score", "ai_confidence_score"):
            assert expected in keys
