"""
AI Matching Service — Phase 6: probabilistic_review_complete → ai_suggested

Stub implementation — no live LLM API calls.

Advisory only: this service NEVER mutates the residual pool. It only reads
the residual and produces ranked suggestions for human review.

Algorithm (stub):
  1. Group residual records by entity (exact match required).
  2. Within each entity group, generate 1:1 candidate pairs.
  3. Compute ai_confidence_score using a weighted similarity formula with
     wider tolerances than the probabilistic layer.
  4. Suppress pairs below AI_MIN_CONFIDENCE.
  5. Sort by (materiality DESC, ai_confidence_score DESC).

Confidence formula (same weights as probabilistic, but entity is implicit):
  ai_confidence = 0.40 * vendor_similarity
                + 0.35 * amount_similarity
                + 0.15 * date_similarity
                + 0.10 * entity_similarity   (always 1.0 — same-entity grouping)

Date tolerance: AI_DATE_TOLERANCE_DAYS = 90 (wider than probabilistic's 60).
Amount: NO blocking — the AI evaluates pairs the probabilistic layer skipped.
Materiality proxy: abs(GL amount) — larger transactions rank higher.

Snapshot must capture: model_used, prompt_version, suggestion_count.
"""

import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List

import pandas as pd
from rapidfuzz import fuzz


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DEFAULT_AI_MODEL:       str   = "stub-v1"
DEFAULT_PROMPT_VERSION: str   = "v1.0.0"
AI_DATE_TOLERANCE_DAYS: int   = 90       # wider than probabilistic's 60
AI_MIN_CONFIDENCE:      float = 0.40     # suppress very low-confidence pairs

_REQUIRED_GL_COLS  = {"gl_id", "Vendor_Normalized", "amount", "transaction_date", "entity"}
_REQUIRED_SUB_COLS = {"subledger_id", "Vendor_Normalized", "amount", "transaction_date", "entity"}


# ---------------------------------------------------------------------------
# Result dataclasses
# ---------------------------------------------------------------------------

@dataclass
class AIMatchRecord:
    """One AI-generated suggestion (pending human review)."""
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
# Similarity helpers
# ---------------------------------------------------------------------------

def _vendor_sim(norm_a: str, norm_b: str) -> float:
    return fuzz.token_sort_ratio(str(norm_a), str(norm_b)) / 100.0


def _amount_sim(amount_a: float, amount_b: float) -> float:
    base = max(abs(amount_a), abs(amount_b), 0.01)
    return max(0.0, 1.0 - abs(amount_a - amount_b) / base)


def _date_sim(date_a, date_b) -> float:
    diff = abs((pd.to_datetime(date_a) - pd.to_datetime(date_b)).days)
    return max(0.0, 1.0 - diff / AI_DATE_TOLERANCE_DAYS)


def _ai_confidence(gl_row, sub_row) -> float:
    """Weighted similarity — entity component is always 1.0 (same-entity grouping)."""
    vendor  = _vendor_sim(gl_row["Vendor_Normalized"], sub_row["Vendor_Normalized"])
    amount  = _amount_sim(float(gl_row["amount"]),     float(sub_row["amount"]))
    date    = _date_sim(gl_row["transaction_date"],    sub_row["transaction_date"])
    return round(0.40 * vendor + 0.35 * amount + 0.15 * date + 0.10 * 1.0, 4)


def _materiality(gl_row) -> float:
    return round(abs(float(gl_row["amount"])), 2)


def _supporting_features(gl_row, sub_row) -> Dict[str, Any]:
    gl_amount   = float(gl_row["amount"])
    sub_amount  = float(sub_row["amount"])
    diff_days   = abs((pd.to_datetime(gl_row["transaction_date"])
                       - pd.to_datetime(sub_row["transaction_date"])).days)
    return {
        "vendor_similarity": round(_vendor_sim(
            gl_row["Vendor_Normalized"], sub_row["Vendor_Normalized"]), 4),
        "amount_diff":      round(abs(gl_amount - sub_amount), 2),
        "amount_diff_pct":  round(
            abs(gl_amount - sub_amount)
            / max(abs(gl_amount), abs(sub_amount), 0.01) * 100, 2),
        "date_diff_days":   diff_days,
        "entity":           str(gl_row["entity"]),
    }


def _reasoning_narrative(gl_id: str, sub_id: str, gl_row, sub_row,
                          confidence: float) -> str:
    gl_amount  = float(gl_row["amount"])
    sub_amount = float(sub_row["amount"])
    amount_diff = abs(gl_amount - sub_amount)
    diff_days   = abs((pd.to_datetime(gl_row["transaction_date"])
                       - pd.to_datetime(sub_row["transaction_date"])).days)
    vendor_pct  = round(
        fuzz.token_sort_ratio(
            str(gl_row["Vendor_Normalized"]), str(sub_row["Vendor_Normalized"])),
        1,
    )
    return (
        f"GL record {gl_id} ('{gl_row['Vendor_Normalized']}', ${gl_amount:,.2f}) and "
        f"Sub record {sub_id} ('{sub_row['Vendor_Normalized']}', ${sub_amount:,.2f}) "
        f"share entity '{gl_row['entity']}' with {vendor_pct}% vendor name similarity. "
        f"Amount difference: ${amount_diff:,.2f} over {diff_days} day(s). "
        f"AI confidence: {confidence:.1%}. Requires human review before acceptance."
    )


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

    Args:
        residual_gl:    GL residual DataFrame. Required columns:
                          gl_id, Vendor_Normalized, amount, transaction_date, entity
        residual_sub:   Sub residual DataFrame. Required columns:
                          subledger_id, Vendor_Normalized, amount, transaction_date, entity
        ai_model:       Model identifier recorded in snapshot (stub: "stub-v1").
        prompt_version: Prompt version recorded in snapshot.

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

    # Column validation
    if len(residual_gl) > 0:
        missing = _REQUIRED_GL_COLS - set(residual_gl.columns)
        if missing:
            raise ValueError(f"GL residual missing required columns: {missing}")
    if len(residual_sub) > 0:
        missing = _REQUIRED_SUB_COLS - set(residual_sub.columns)
        if missing:
            raise ValueError(f"Sub residual missing required columns: {missing}")

    suggestions: List[AIMatchRecord] = []

    # Group by entity — AI only compares records within the same entity
    entities = sorted(
        set(residual_gl["entity"].dropna().unique()) &
        set(residual_sub["entity"].dropna().unique())
    )

    for entity in entities:
        gl_e  = residual_gl[residual_gl["entity"] == entity]
        sub_e = residual_sub[residual_sub["entity"] == entity]

        for _, gl_row in gl_e.iterrows():
            gl_id = str(gl_row["gl_id"])
            for _, sub_row in sub_e.iterrows():
                sub_id     = str(sub_row["subledger_id"])
                confidence = _ai_confidence(gl_row, sub_row)

                if confidence < AI_MIN_CONFIDENCE:
                    continue

                mat      = _materiality(gl_row)
                features = _supporting_features(gl_row, sub_row)
                narrative = _reasoning_narrative(gl_id, sub_id, gl_row, sub_row,
                                                 confidence)

                suggestions.append(AIMatchRecord(
                    match_id=            str(uuid.uuid4()),
                    record_ids_A=        [gl_id],
                    record_ids_B=        [sub_id],
                    ai_confidence_score= confidence,
                    materiality=         mat,
                    supporting_features= features,
                    reasoning_narrative= narrative,
                ))

    # Rank: materiality DESC, then confidence DESC
    suggestions.sort(key=lambda s: (-s.materiality, -s.ai_confidence_score))

    return AIMatchingResult(
        suggestions=        suggestions,
        total_residual_gl=  total_gl,
        total_residual_sub= total_sub,
        model_used=         ai_model,
        prompt_version=     prompt_version,
    )
