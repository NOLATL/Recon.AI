"""
AI Matching Service — Phase 6: probabilistic_review_complete → ai_suggested

Uses OpenAI to suggest matches from the residual pool.
Advisory only: the residual pool is NEVER modified by this service.

Grouping strategy — per (entity, Vendor_Normalized):
  Within each entity, records are further sub-grouped by normalized vendor name.
  Each LLM call receives only the GL and Sub records sharing the same entity AND
  vendor — keeping prompts small and preventing cross-vendor hallucinations.
  Records whose normalized vendor name has no counterpart on the other side are
  skipped (the AI cannot match what has nothing to compare against).

N:M grouping is fully supported:
  1:1 → one_to_one
  N:1 → many_to_one
  1:N → one_to_many
  N:M → many_to_many

Confidence scale: 0.0–1.0. Minimum: AI_MIN_CONFIDENCE (0.40).

On LLM failure (network, JSON parse, etc.) for any group:
  - That group is silently skipped with a warning log.
  - The session is never failed — this is an advisory-only layer.

Model: gpt-4o-mini (cost-effective, fully capable for structured JSON).
Prompt version: v2.0.0 (stored in snapshot for audit reproducibility).
"""

import json
import logging
import uuid
from dataclasses import dataclass
from typing import Any, Dict, List, Set

import pandas as pd
from rapidfuzz import fuzz

from src.llm.openai_client import OpenAIClient


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DEFAULT_AI_MODEL:        str   = "gpt-4o-mini"
DEFAULT_PROMPT_VERSION:  str   = "v2.0.0"
AI_MIN_CONFIDENCE:       float = 0.40
MAX_RECORDS_PER_GROUP:   int   = 20   # per (entity, vendor) call — controls token cost

_REQUIRED_GL_COLS  = {"gl_id", "Vendor_Normalized", "amount", "transaction_date", "entity"}
_REQUIRED_SUB_COLS = {"subledger_id", "Vendor_Normalized", "amount", "transaction_date", "entity"}

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# System prompt (versioned — stored in snapshot for reproducibility)
# ---------------------------------------------------------------------------

_SYSTEM_PROMPT = """\
You are a financial reconciliation specialist.

You will receive GL records and Subledger records that belong to the SAME legal \
entity and SAME vendor. Rule-based algorithms did not confidently match them — \
typically due to timing differences, partial payments, or accrual adjustments.

Your task: identify which GL records match which Subledger records.

Matching criteria:
- Amount: When entity, vendor, and date align, you MUST suggest a match if amount \
variance is 25% or less — do not return empty. Partial payments and accruals \
commonly have 10–25% variance. Example: GL $1000 vs Sub $1150 (15% diff) = valid \
match, suggest confidence 0.70–0.85. One GL may cover multiple Sub lines or vice versa.
- Date: within 90 days is acceptable; use judgement for borderline cases
- A GL record MAY match multiple Subledger records (1:N) if their amounts sum \
close to the GL amount
- Multiple GL records MAY match one Subledger record (N:1) if their amounts sum \
close to the Sub amount

Rules:
- Each record ID may appear in at most ONE match in your output
- Only suggest matches with confidence >= 0.40
- If no match meets that bar, return an empty matches array
- Return ONLY the JSON object — no explanation, no markdown, no text outside the JSON

Output format:
{
  "matches": [
    {
      "gl_ids":     ["<gl_id>"],
      "sub_ids":    ["<subledger_id>"],
      "confidence": <float 0.0–1.0>,
      "reasoning":  "<one sentence for the reviewer>"
    }
  ]
}"""


# ---------------------------------------------------------------------------
# Result dataclasses
# ---------------------------------------------------------------------------

@dataclass
class AIMatchRecord:
    """One AI-generated match suggestion (pending human review)."""
    match_id:            str
    record_ids_A:        List[str]   # GL IDs
    record_ids_B:        List[str]   # Subledger IDs
    ai_confidence_score: float
    materiality:         float
    supporting_features: Dict[str, Any]
    reasoning_narrative: str
    grouping_type:       str  = "one_to_one"
    user_status:         str  = "pending"
    override_flag:       bool = False

    def to_dict(self) -> dict:
        return {
            "match_id":            self.match_id,
            "record_ids_A":        self.record_ids_A,
            "record_ids_B":        self.record_ids_B,
            "ai_confidence_score": self.ai_confidence_score,
            "materiality":         self.materiality,
            "supporting_features": self.supporting_features,
            "reasoning_narrative": self.reasoning_narrative,
            "grouping_type":       self.grouping_type,
            "user_status":         self.user_status,
            "override_flag":       self.override_flag,
        }


@dataclass
class AIMatchingResult:
    """Full output of run_ai_matching()."""
    suggestions:        List[AIMatchRecord]
    total_residual_gl:  int
    total_residual_sub: int
    model_used:         str
    prompt_version:     str

    def to_suggestion_list(self) -> List[dict]:
        return [s.to_dict() for s in self.suggestions]


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _grouping_type(n_gl: int, n_sub: int) -> str:
    if n_gl == 1 and n_sub == 1:
        return "one_to_one"
    if n_gl > 1 and n_sub == 1:
        return "many_to_one"
    if n_gl == 1 and n_sub > 1:
        return "one_to_many"
    return "many_to_many"


def _materiality(gl_ids: List[str], gl_amount_lookup: Dict[str, float]) -> float:
    return round(sum(abs(gl_amount_lookup.get(gid, 0.0)) for gid in gl_ids), 2)


def _supporting_features(
    gl_ids:     List[str],
    sub_ids:    List[str],
    gl_lookup:  Dict[str, dict],
    sub_lookup: Dict[str, dict],
) -> Dict[str, Any]:
    gl  = gl_lookup[gl_ids[0]]
    sub = sub_lookup[sub_ids[0]]

    gl_total  = sum(gl_lookup[gid]["amount"] for gid in gl_ids)
    sub_total = sum(sub_lookup[sid]["amount"] for sid in sub_ids)

    vendor_sim      = round(fuzz.token_sort_ratio(
        str(gl["Vendor_Normalized"]), str(sub["Vendor_Normalized"])) / 100.0, 4)
    amount_diff     = round(abs(gl_total - sub_total), 2)
    base            = max(abs(gl_total), abs(sub_total), 0.01)
    amount_diff_pct = round(amount_diff / base * 100, 2)
    diff_days       = abs(
        (pd.to_datetime(gl["transaction_date"])
         - pd.to_datetime(sub["transaction_date"])).days
    )

    return {
        "vendor_similarity": vendor_sim,
        "amount_diff":       amount_diff,
        "amount_diff_pct":   amount_diff_pct,
        "date_diff_days":    diff_days,
        "entity":            str(gl["entity"]),
    }


def _call_llm(
    entity:      str,
    vendor:      str,
    gl_records:  list,
    sub_records: list,
    ai_model:    str,
) -> List[dict]:
    """
    Call OpenAI for one (entity, vendor) group.
    Returns the parsed matches list, or [] on any failure.
    Never raises — the advisory layer must not crash the session.
    """
    user_prompt = (
        f"Entity: {entity}\n"
        f"Vendor: {vendor}\n\n"
        f"GL Records:\n{json.dumps(gl_records, indent=2)}\n\n"
        f"Subledger Records:\n{json.dumps(sub_records, indent=2)}\n\n"
        "Suggest matches."
    )
    print(f"[AI DEBUG] Calling LLM: entity={entity!r} vendor={vendor!r} gl={len(gl_records)} sub={len(sub_records)}")
    try:
        client = OpenAIClient(model=ai_model)
        result = client.generate_json(_SYSTEM_PROMPT, user_prompt)
        matches = result.get("matches", [])
        print(f"[AI DEBUG] LLM response: matches_count={len(matches)} raw={json.dumps(result)[:800]}")
        return matches
    except Exception as exc:
        logger.warning(
            "AI matching call failed for entity=%s vendor=%s: %s", entity, vendor, exc
        )
        return []


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def run_ai_matching(
    residual_gl:    pd.DataFrame,
    residual_sub:   pd.DataFrame,
    ai_model:       str = DEFAULT_AI_MODEL,
    prompt_version: str = DEFAULT_PROMPT_VERSION,
) -> AIMatchingResult:
    """
    Generate AI-assisted match suggestions from the residual pool.

    Advisory only — the residual pool is never modified.

    Groups records by (entity, Vendor_Normalized) and makes one LLM call per
    group. Each record ID may appear in at most one suggestion (deduplicated
    across groups in score order after ranking).

    Args:
        residual_gl:    GL residual DataFrame. Required columns:
                          gl_id, Vendor_Normalized, amount, transaction_date, entity
        residual_sub:   Sub residual DataFrame. Required columns:
                          subledger_id, Vendor_Normalized, amount, transaction_date, entity
        ai_model:       Model ID passed to OpenAIClient.
        prompt_version: Version tag stored in snapshot for reproducibility.

    Returns:
        AIMatchingResult — suggestions ranked by materiality DESC, confidence DESC.

    Raises:
        ValueError — if a required column is missing from a non-empty DataFrame.
    """
    total_gl  = len(residual_gl)
    total_sub = len(residual_sub)

    if total_gl == 0 or total_sub == 0:
        return AIMatchingResult(
            suggestions=[],
            total_residual_gl=total_gl,
            total_residual_sub=total_sub,
            model_used=ai_model,
            prompt_version=prompt_version,
        )

    if total_gl > 0:
        missing = _REQUIRED_GL_COLS - set(residual_gl.columns)
        if missing:
            raise ValueError(f"GL residual missing required columns: {missing}")
    if total_sub > 0:
        missing = _REQUIRED_SUB_COLS - set(residual_sub.columns)
        if missing:
            raise ValueError(f"Sub residual missing required columns: {missing}")

    # Build ID-keyed lookup dicts for validation and feature computation.
    gl_lookup: Dict[str, dict] = {}
    for _, row in residual_gl.iterrows():
        gid = str(row["gl_id"])
        gl_lookup[gid] = {
            "gl_id":             gid,
            "Vendor_Normalized": str(row["Vendor_Normalized"]),
            "amount":            float(row["amount"]),
            "transaction_date":  str(row["transaction_date"]),
            "entity":            str(row["entity"]),
        }

    sub_lookup: Dict[str, dict] = {}
    for _, row in residual_sub.iterrows():
        sid = str(row["subledger_id"])
        sub_lookup[sid] = {
            "subledger_id":      sid,
            "Vendor_Normalized": str(row["Vendor_Normalized"]),
            "amount":            float(row["amount"]),
            "transaction_date":  str(row["transaction_date"]),
            "entity":            str(row["entity"]),
        }

    gl_amount_lookup: Dict[str, float] = {gid: r["amount"] for gid, r in gl_lookup.items()}

    entities = sorted(
        set(residual_gl["entity"].dropna().unique()) &
        set(residual_sub["entity"].dropna().unique())
    )

    suggestions:  List[AIMatchRecord] = []
    used_gl_ids:  Set[str] = set()
    used_sub_ids: Set[str] = set()

    for entity in entities:
        gl_e  = residual_gl[residual_gl["entity"] == entity]
        sub_e = residual_sub[residual_sub["entity"] == entity]

        # Vendor intersection: only groups where both sides have records.
        vendors = sorted(
            set(gl_e["Vendor_Normalized"].dropna().unique()) &
            set(sub_e["Vendor_Normalized"].dropna().unique())
        )

        for vendor in vendors:
            gl_v  = gl_e[gl_e["Vendor_Normalized"] == vendor].head(MAX_RECORDS_PER_GROUP)
            sub_v = sub_e[sub_e["Vendor_Normalized"] == vendor].head(MAX_RECORDS_PER_GROUP)

            # Exclude records already consumed by a prior group.
            gl_v  = gl_v[~gl_v["gl_id"].astype(str).isin(used_gl_ids)]
            sub_v = sub_v[~sub_v["subledger_id"].astype(str).isin(used_sub_ids)]

            if gl_v.empty or sub_v.empty:
                continue

            valid_gl_ids  = set(gl_v["gl_id"].astype(str))
            valid_sub_ids = set(sub_v["subledger_id"].astype(str))

            gl_records = [
                {
                    "gl_id":  str(r["gl_id"]),
                    "vendor": str(r["Vendor_Normalized"]),
                    "amount": float(r["amount"]),
                    "date":   str(r["transaction_date"]),
                }
                for _, r in gl_v.iterrows()
            ]
            sub_records = [
                {
                    "subledger_id": str(r["subledger_id"]),
                    "vendor":       str(r["Vendor_Normalized"]),
                    "amount":       float(r["amount"]),
                    "date":         str(r["transaction_date"]),
                }
                for _, r in sub_v.iterrows()
            ]

            raw_matches = _call_llm(entity, vendor, gl_records, sub_records, ai_model)

            for raw in raw_matches:
                try:
                    gl_ids     = [str(x) for x in raw.get("gl_ids",  [])]
                    sub_ids    = [str(x) for x in raw.get("sub_ids", [])]
                    confidence = float(raw.get("confidence", 0.0))
                    reasoning  = str(raw.get("reasoning", ""))

                    if not gl_ids or not sub_ids:
                        continue
                    if confidence < AI_MIN_CONFIDENCE:
                        continue
                    confidence = min(1.0, max(0.0, confidence))

                    # All IDs must belong to this (entity, vendor) group.
                    if not all(gid in valid_gl_ids  for gid in gl_ids):
                        continue
                    if not all(sid in valid_sub_ids for sid in sub_ids):
                        continue

                    # Cross-group deduplication — each ID appears in at most one match.
                    if any(gid in used_gl_ids  for gid in gl_ids):
                        continue
                    if any(sid in used_sub_ids for sid in sub_ids):
                        continue

                    used_gl_ids.update(gl_ids)
                    used_sub_ids.update(sub_ids)

                    suggestions.append(AIMatchRecord(
                        match_id=            str(uuid.uuid4()),
                        record_ids_A=        gl_ids,
                        record_ids_B=        sub_ids,
                        ai_confidence_score= round(confidence, 4),
                        materiality=         _materiality(gl_ids, gl_amount_lookup),
                        supporting_features= _supporting_features(
                            gl_ids, sub_ids, gl_lookup, sub_lookup
                        ),
                        reasoning_narrative= reasoning,
                        grouping_type=       _grouping_type(len(gl_ids), len(sub_ids)),
                    ))
                except Exception as exc:
                    logger.warning("Skipping invalid AI suggestion: %s — %s", raw, exc)
                    continue

    # Rank: materiality DESC, then confidence DESC.
    suggestions.sort(key=lambda s: (-s.materiality, -s.ai_confidence_score))

    return AIMatchingResult(
        suggestions=        suggestions,
        total_residual_gl=  total_gl,
        total_residual_sub= total_sub,
        model_used=         ai_model,
        prompt_version=     prompt_version,
    )
