"""
Vendor Normalization Pipeline — Phase 3: profiled → preprocessed

Three-tier cascade:

  Tier 1 — Deterministic preprocessing
    Steps (applied in order):
      1. Pre-normalization alias lookup (original string → canonical alias)
      2. Lowercase + Unicode NFC normalization
      3. Punctuation removal (non-word, non-space chars → space)
      4. Collapse whitespace
      5. Corporate suffix stripping (trailing tokens only)
      6. Stopword removal
    Tag: match_source = "preprocessing"

  Tier 2 — NLP (RapidFuzz token_sort_ratio)
    Applied to GL vendors not resolved in Tier 1.
    Compares the tier-1-normalized GL form against all tier-1-normalized
    Subledger forms.
    Scorer: token_sort_ratio — sorts tokens alphabetically before comparing, so
      word-order variation is handled without the false-positive inflation of
      token_set_ratio (which can return 100 whenever one string's tokens are a
      strict subset of the other, e.g. "vendor" vs "unique vendor xyz").
    Threshold: runtime["config"]["vendor_nlp_threshold"] (default 0.90, i.e. 90%)
    RapidFuzz returns 0–100; threshold is stored as 0.0–1.0 → compare score ≥ threshold * 100.
    Tag: match_source = "nlp", similarity_score stored as 0.0–1.0

  Tier 3 — AI residual stub
    Applied to GL vendors not resolved in Tier 1 or Tier 2.
    No API call yet — placeholder for future AI disambiguation.
    Tag: match_source = "ai", ai_confidence_score = None

Output contract:
  - vendor_normalization_map: one NormalizationEntry per unique GL vendor_name
  - GL DataFrame gains column "Vendor_Normalized"
  - Subledger DataFrame gains column "Vendor_Normalized"

Vendor_Normalized semantics:
  For tier-1 and tier-2 matches, Vendor_Normalized equals the normalized form of
  the *matched Subledger vendor*.  This ensures GL and Subledger rows that were
  resolved to the same entity share an identical Vendor_Normalized key, enabling
  a simple equality join in downstream deterministic matching.
  For tier-3 (no match), Vendor_Normalized is the normalized form of the GL vendor.

Design rules:
  - Pure function: run_normalization() has no side effects on the runtime.
  - Deterministic for Tier 1: same input always produces the same output.
  - alias_map is applied BEFORE text normalization (maps original strings to canonical names).
  - All normalization steps operate on lower-cased text to avoid case sensitivity.
"""

import re
import unicodedata
from dataclasses import dataclass
from typing import Dict, List, Optional

import pandas as pd
from rapidfuzz import fuzz, process

# ---------------------------------------------------------------------------
# Tier 3 — AI constants
# ---------------------------------------------------------------------------

_AI_SYSTEM_PROMPT = (
    "You are a financial data reconciliation assistant.\n\n"
    "Your task is to find the single best matching subledger vendor for a given GL vendor name.\n\n"
    "Use common business knowledge, abbreviations, and vendor naming conventions.\n\n"
    "Examples of valid matches:\n"
    "  AWS → Amazon Web Services\n"
    "  Amazon Web Srvcs → Amazon Web Services\n"
    "  HD Supply → Home Depot Supply\n"
    "  WMT → Walmart\n\n"
    "Return ONLY valid JSON with no markdown, no code fences."
)


def _ai_batch_user_prompt(gl_vendor: str, sub_vendors: List[str]) -> str:
    vendors_list = "\n".join(f"- {v}" for v in sub_vendors)
    return (
        f"Find the best matching subledger vendor for this GL vendor name.\n\n"
        f"GL Vendor: {gl_vendor}\n\n"
        f"Subledger Vendors:\n{vendors_list}\n\n"
        'Return JSON: {"matched_vendor": "exact string from list or null", "confidence": 0.0, "reason": "one sentence"}\n\n'
        "Rules:\n"
        "* matched_vendor must be an exact string copied verbatim from the list above, or null\n"
        "* confidence must be between 0 and 1\n"
        "* if no good match exists, set matched_vendor to null and confidence to 0\n"
        "* output ONLY JSON"
    )


# Minimum AI confidence to treat a match as valid
_AI_MATCH_THRESHOLD = 0.70


# ---------------------------------------------------------------------------
# Normalization constants
# ---------------------------------------------------------------------------

# Trailing corporate suffixes stripped in tier 1 (all lowercase, no punctuation)
_CORPORATE_SUFFIXES: frozenset = frozenset([
    "llc", "ltd", "limited", "inc", "incorporated",
    "corp", "corporation", "co", "company",
    "plc", "gmbh", "ag", "sa", "sas", "bv", "nv",
    "pty", "pte", "ab", "as", "oy",
    "llp", "lp", "lllp", "pllc", "pc", "pa",
    "intl", "international", "group", "holdings", "holding",
    "enterprises", "enterprise", "services", "service",
    "solutions", "solution", "technologies", "technology", "tech",
    "industries", "industry",
])

# Stopwords removed after suffix stripping.
# "a" and "an" are intentionally excluded: in company names a lone letter or
# short abbreviation (e.g. "Vendor A", "A&B Corp") carries identity, not
# grammatical noise.  Removing them would collapse "Vendor A" → "vendor",
# erasing a meaningful differentiator.
_STOPWORDS: frozenset = frozenset([
    "the", "and", "of", "for", "in", "on",
    "at", "to", "by", "with", "or", "from",
])

DEFAULT_ALIAS_VERSION = "v1.0.0"


# ---------------------------------------------------------------------------
# Result dataclasses
# ---------------------------------------------------------------------------

@dataclass
class NormalizationEntry:
    """One mapping record for a unique GL vendor_name value."""
    original_vendor: str
    normalized_vendor: str          # tier-1 text transformation of the GL vendor
    matched_to: Optional[str]       # original Subledger vendor that was matched (or None)
    match_source: str               # "preprocessing" | "nlp" | "ai"
    similarity_score: Optional[float]       # 0.0–1.0, nlp tier only
    ai_confidence_score: Optional[float]    # placeholder, ai tier only

    def to_dict(self) -> dict:
        return {
            "original_vendor":      self.original_vendor,
            "normalized_vendor":    self.normalized_vendor,
            "matched_to":           self.matched_to,
            "match_source":         self.match_source,
            "similarity_score":     self.similarity_score,
            "ai_confidence_score":  self.ai_confidence_score,
        }


@dataclass
class NormalizationResult:
    """Full output of run_normalization()."""
    entries:                  List[NormalizationEntry]
    gl_df:                    pd.DataFrame    # GL with Vendor_Normalized column added
    sub_df:                   pd.DataFrame    # Subledger with Vendor_Normalized column added
    tier1_count:              int
    tier2_count:              int
    tier3_count:              int
    threshold_used:           float
    alias_version:            str
    unmatched_sub_vendors:    List[str]           # Sub vendors not matched by any GL entry
    unmatched_sub_normalized: Dict[str, str]      # original → normalized for unmatched subs

    def to_map_list(self) -> List[dict]:
        return [e.to_dict() for e in self.entries]


# ---------------------------------------------------------------------------
# Tier 1 text normalization helpers
# ---------------------------------------------------------------------------

def normalize_vendor(vendor: str, alias_map: Dict[str, str]) -> str:
    """
    Apply all tier-1 normalization steps to a single vendor string.

    Steps (in order):
      1. Pre-normalization alias substitution on the original string
      2. Lowercase + Unicode NFC
      3. Punctuation → space
      4. Collapse whitespace
      5. Strip trailing corporate suffixes (iterative — handles stacked suffixes)
      6. Remove stopwords

    Returns the normalized string (may be empty if the vendor collapses entirely).
    Exported so callers can normalize individual strings without running the
    full pipeline.
    """
    if not vendor or (isinstance(vendor, float) and pd.isna(vendor)):
        return ""

    # Step 1 — pre-normalization alias lookup (original form)
    vendor = alias_map.get(vendor, vendor)

    # Step 2 — lowercase + Unicode NFC
    text = unicodedata.normalize("NFC", str(vendor).lower().strip())

    # Step 3 — punctuation removal (replace non-word, non-space with space)
    text = re.sub(r"[^\w\s]", " ", text)

    # Step 4 — collapse whitespace
    text = re.sub(r"\s+", " ", text).strip()

    # Step 5 — strip trailing corporate suffixes (iterative for stacked suffixes)
    tokens = text.split()
    changed = True
    while changed and tokens:
        changed = False
        if tokens[-1] in _CORPORATE_SUFFIXES:
            tokens.pop()
            changed = True
    text = " ".join(tokens).strip()

    # Step 6 — stopword removal
    tokens = [t for t in text.split() if t not in _STOPWORDS]
    return " ".join(tokens).strip()


# ---------------------------------------------------------------------------
# Main pipeline entry point
# ---------------------------------------------------------------------------

def run_normalization(
    gl_df:          pd.DataFrame,
    sub_df:         pd.DataFrame,
    nlp_threshold:  float = 0.90,
    alias_map:      Optional[Dict[str, str]] = None,
    alias_version:  str = DEFAULT_ALIAS_VERSION,
) -> NormalizationResult:
    """
    Run the 3-tier vendor normalization pipeline.

    Args:
        gl_df:          GL DataFrame — must contain a 'vendor_name' column.
        sub_df:         Subledger DataFrame — must contain a 'vendor_name' column.
        nlp_threshold:  Minimum RapidFuzz similarity for a tier-2 match (0.0–1.0).
                        Compared as ``score >= nlp_threshold * 100`` where score is
                        the 0–100 value returned by rapidfuzz.
        alias_map:      Config-driven dict mapping known alias strings to canonical
                        names.  Applied BEFORE text normalization.
        alias_version:  Version tag for the alias configuration (for audit logging).

    Returns:
        NormalizationResult — mapping entries + enriched GL/Sub DataFrames.

    Raises:
        ValueError — if 'vendor_name' column is absent from either DataFrame.
    """
    if alias_map is None:
        alias_map = {}

    if "vendor_name" not in gl_df.columns:
        raise ValueError("GL DataFrame is missing required 'vendor_name' column.")
    if "vendor_name" not in sub_df.columns:
        raise ValueError("Subledger DataFrame is missing required 'vendor_name' column.")

    # -----------------------------------------------------------------------
    # Collect unique non-null vendor strings from each file
    # -----------------------------------------------------------------------
    gl_unique:  List[str] = [v for v in gl_df["vendor_name"].dropna().unique().tolist()]
    sub_unique: List[str] = [v for v in sub_df["vendor_name"].dropna().unique().tolist()]

    # -----------------------------------------------------------------------
    # Tier 1 — apply text normalization to all vendors
    # -----------------------------------------------------------------------
    # Maps original string → normalized form
    gl_norm:  Dict[str, str] = {v: normalize_vendor(v, alias_map) for v in gl_unique}
    sub_norm: Dict[str, str] = {v: normalize_vendor(v, alias_map) for v in sub_unique}

    # Reverse map: normalized_sub_form → original_sub_vendor
    # If two Sub vendors normalize to the same form, last one wins (edge case).
    norm_to_sub_orig: Dict[str, str] = {norm: orig for orig, norm in sub_norm.items()}
    norm_sub_forms:   List[str] = list(sub_norm.values())

    # -----------------------------------------------------------------------
    # Cascade: tier 1 → tier 2 → tier 3
    # -----------------------------------------------------------------------
    entries:         List[NormalizationEntry] = []
    tier2_candidates: List[str] = []   # GL vendors not resolved by tier 1

    # --- Tier 1: exact normalized match ---
    for orig in gl_unique:
        norm = gl_norm[orig]
        if norm in norm_to_sub_orig:
            entries.append(NormalizationEntry(
                original_vendor=    orig,
                normalized_vendor=  norm,
                matched_to=         norm_to_sub_orig[norm],
                match_source=       "preprocessing",
                similarity_score=   None,
                ai_confidence_score=None,
            ))
        else:
            tier2_candidates.append(orig)

    # --- Tier 2: RapidFuzz token_sort_ratio ---
    # token_sort_ratio sorts both strings' tokens alphabetically before comparing,
    # handling word-order variation without the false-positive inflation of
    # token_set_ratio (which scores 100 when one string's tokens are a subset
    # of the other — e.g. "vendor" subset of "unique vendor xyz").
    tier3_candidates: List[str] = []

    if tier2_candidates and norm_sub_forms:
        cutoff = nlp_threshold * 100          # rapidfuzz operates on 0–100 scale
        for orig in tier2_candidates:
            query = gl_norm[orig] or orig.lower()
            best = process.extractOne(
                query,
                norm_sub_forms,
                scorer=fuzz.token_sort_ratio,
                score_cutoff=cutoff,
            )
            if best is not None:
                best_norm_sub, score, _ = best
                entries.append(NormalizationEntry(
                    original_vendor=    orig,
                    normalized_vendor=  gl_norm[orig],
                    matched_to=         norm_to_sub_orig.get(best_norm_sub),
                    match_source=       "nlp",
                    similarity_score=   round(score / 100.0, 4),
                    ai_confidence_score=None,
                ))
            else:
                tier3_candidates.append(orig)
    else:
        tier3_candidates = tier2_candidates

    # --- Tier 3: AI vendor resolution ---
    # Attempt to resolve remaining unmatched GL vendors via OpenAI.
    # For each tier-3 GL vendor, compare against every Sub vendor and take the
    # highest-confidence match that meets _AI_MATCH_THRESHOLD.
    # Degrades silently if OPENAI_API_KEY is not set or a call fails.
    ai_client = None
    if tier3_candidates:
        try:
            from src.llm.openai_client import OpenAIClient
            ai_client = OpenAIClient()
        except Exception:
            pass  # No API key or import error — fall back to unmatched

    for orig in tier3_candidates:
        best_sub:        Optional[str] = None
        best_normalized: Optional[str] = None
        best_confidence: float         = 0.0

        if ai_client is not None and sub_unique:
            try:
                result     = ai_client.generate_json(
                    _AI_SYSTEM_PROMPT,
                    _ai_batch_user_prompt(orig, sub_unique),
                )
                matched    = result.get("matched_vendor")
                confidence = float(result.get("confidence", 0))
                # Accept only if the returned string is an exact member of sub_unique
                if matched and matched in sub_unique and confidence >= _AI_MATCH_THRESHOLD:
                    best_confidence = confidence
                    best_normalized = str(matched)
                    best_sub        = matched
            except Exception:
                pass  # malformed JSON or API error — record as unmatched

        if best_sub is not None:
            entries.append(NormalizationEntry(
                original_vendor=    orig,
                normalized_vendor=  best_normalized,
                matched_to=         best_sub,
                match_source=       "ai",
                similarity_score=   None,
                ai_confidence_score=best_confidence,
            ))
        else:
            # No confident AI match — record as unmatched with zero confidence
            entries.append(NormalizationEntry(
                original_vendor=    orig,
                normalized_vendor=  gl_norm[orig],
                matched_to=         None,
                match_source=       "ai",
                similarity_score=   None,
                ai_confidence_score=0.0,
            ))

    # -----------------------------------------------------------------------
    # Tier counts
    # -----------------------------------------------------------------------
    tier1_count = sum(1 for e in entries if e.match_source == "preprocessing")
    tier2_count = sum(1 for e in entries if e.match_source == "nlp")
    tier3_count = sum(1 for e in entries if e.match_source == "ai")

    # -----------------------------------------------------------------------
    # Build Vendor_Normalized lookup for GL
    #
    # For tier-1 and tier-2 matches: use the normalized form of the matched
    # Subledger vendor.  This ensures GL and Sub share an identical key for
    # the matched entity, enabling a direct equality join downstream.
    # For tier-3: fall back to the normalized GL vendor form.
    # -----------------------------------------------------------------------
    gl_vendor_normalized: Dict[str, str] = {}
    for e in entries:
        if e.matched_to and e.matched_to in sub_norm:
            # canonical key = normalized form of the matched Sub vendor
            gl_vendor_normalized[e.original_vendor] = sub_norm[e.matched_to]
        else:
            gl_vendor_normalized[e.original_vendor] = e.normalized_vendor

    # -----------------------------------------------------------------------
    # Enrich DataFrames — preserve originals, add Vendor_Normalized column
    # -----------------------------------------------------------------------
    gl_out = gl_df.copy()
    gl_out["Vendor_Normalized"] = gl_out["vendor_name"].map(
        lambda v: gl_vendor_normalized.get(v, normalize_vendor(str(v), alias_map))
        if pd.notna(v) else None
    )

    sub_out = sub_df.copy()
    sub_out["Vendor_Normalized"] = sub_out["vendor_name"].map(
        lambda v: sub_norm.get(v, normalize_vendor(str(v), alias_map))
        if pd.notna(v) else None
    )

    # Subledger vendors not claimed by any GL entry
    matched_subs = {e.matched_to for e in entries if e.matched_to is not None}
    unmatched_sub_vendors = [v for v in sub_unique if v not in matched_subs]
    unmatched_sub_normalized = {v: sub_norm.get(v, normalize_vendor(v, alias_map))
                                 for v in unmatched_sub_vendors}

    return NormalizationResult(
        entries=                  entries,
        gl_df=                    gl_out,
        sub_df=                   sub_out,
        tier1_count=              tier1_count,
        tier2_count=              tier2_count,
        tier3_count=              tier3_count,
        threshold_used=           nlp_threshold,
        alias_version=            alias_version,
        unmatched_sub_vendors=    unmatched_sub_vendors,
        unmatched_sub_normalized= unmatched_sub_normalized,
    )
