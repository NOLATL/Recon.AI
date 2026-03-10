"""
Summary Narrative Service — post-reconciliation AI narrative generator.

Uses OpenAI to produce a 3-paragraph summary covering:
  1. Processing overview — phases run, data volumes, methods used.
  2. Results summary    — match counts / rates by layer, residual exposure.
  3. Patterns & suggestions — what drove residuals, how to improve future runs.

Falls back to a deterministic template if OPENAI_API_KEY is absent or the
API call fails for any reason.

Model: gpt-4o-mini (same as AI matching — cost-effective capable model).
"""

import json
from typing import Any, Dict


_SYSTEM_PROMPT = """\
You are a financial reconciliation analyst writing a post-reconciliation summary \
for a CFO and finance team.

The reconciliation used three sequential matching layers:
1. Deterministic — exact rule-based matching (highest confidence, authoritative).
2. Probabilistic — similarity-score-based matching (vendor, amount, date proximity).
3. AI            — LLM-powered advisory matching for hard-to-match residuals.

Write a concise narrative in exactly 3 short paragraphs separated by blank lines:

  Paragraph 1 — Processing overview: what phases ran, at what data volumes, and
    which matching methods were applied.
  Paragraph 2 — Results summary: match counts and rates by layer, total matched vs
    unmatched records, and dollar exposure of any residuals where available.
  Paragraph 3 — Patterns, takeaways, and concrete suggestions to improve future
    match rates (e.g. vendor normalization gaps, timing differences, partial
    payments, threshold tuning).

Be direct and professional. Use the numbers from the data provided. Return plain
text only — no markdown, no bullet points, no section headers.\
"""


def _deterministic_narrative(data: Dict[str, Any]) -> str:
    """Rule-based fallback summary — no external calls."""
    s    = data.get("summary", {})
    total = s.get("total_match_count", 0) + s.get("residual_gl_count", 0)
    det   = s.get("deterministic_match_count", 0)
    prob  = s.get("probabilistic_match_count", 0)
    ai    = s.get("ai_match_count", 0)
    res_gl  = s.get("residual_gl_count", 0)
    res_sub = s.get("residual_sub_count", 0)
    rejected = s.get("rejected_count", 0)
    rate = (s.get("total_match_count", 0) / total * 100) if total > 0 else 0.0

    p1 = (
        f"The reconciliation processed {total:,} GL transactions through three sequential matching "
        f"layers: deterministic rule-based matching, probabilistic similarity scoring, and "
        f"AI-assisted advisory matching."
    )
    p2 = (
        f"A total of {s.get('total_match_count', 0):,} records were matched ({rate:.1f}% match rate): "
        f"{det:,} via deterministic matching, {prob:,} via probabilistic matching, and {ai:,} via AI. "
        f"{res_gl:,} GL records and {res_sub:,} subledger records remain unmatched."
        + (f" {rejected:,} match candidates were rejected during human review." if rejected > 0 else "")
    )
    p3 = (
        "Review unmatched records for vendor naming inconsistencies, timing differences "
        "exceeding the matching tolerance window, or partial payments split across multiple "
        "transactions. Consider refining the vendor normalization alias table and adjusting "
        "the probabilistic similarity threshold for high-volume, low-variance vendor pairs "
        "to improve future match rates."
    )
    return f"{p1}\n\n{p2}\n\n{p3}"


def generate_summary_narrative(
    data: Dict[str, Any],
    ai_model: str = "gpt-4o-mini",
) -> str:
    """
    Generate a post-reconciliation narrative summary.

    Args:
        data:     dict with a ``summary`` key holding ConsolidationSummary-like
                  counts (deterministic_match_count, probabilistic_match_count,
                  ai_match_count, total_match_count, residual_gl_count,
                  residual_sub_count, rejected_count, override_count).
                  Optional keys: matched_amount, unmatched_amount.
        ai_model: OpenAI model ID (defaults to gpt-4o-mini).

    Returns:
        Plain-text narrative string (3 paragraphs).
    """
    try:
        from src.llm.openai_client import OpenAIClient  # lazy import
        client = OpenAIClient(model=ai_model)
        user_prompt = (
            "Reconciliation results:\n\n"
            f"{json.dumps(data, indent=2)}\n\n"
            "Write the 3-paragraph summary."
        )
        text = client.generate_text(_SYSTEM_PROMPT, user_prompt, temperature=0, max_tokens=600)
        if text:
            return text
    except Exception:
        pass  # API key absent, network error, or any other issue — use fallback

    return _deterministic_narrative(data)
