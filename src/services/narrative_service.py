"""
Narrative service — generates a human-readable profiling summary.

Primary path: OpenAI via OpenAIClient.
Fallback:     Deterministic template if OPENAI_API_KEY is absent or the call fails.
"""

import json
from typing import Any, Dict


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _deterministic_narrative(metrics: Dict[str, Any]) -> str:
    """Rule-based fallback summary — no external calls."""
    files      = metrics.get("files", {})
    cross      = metrics.get("cross_file", {})
    gl         = files.get("gl", {})
    sub        = files.get("subledger", {})
    coa        = files.get("chart_of_accounts", {})

    gl_rows  = gl.get("row_count",  0)
    sub_rows = sub.get("row_count", 0)
    coa_rows = coa.get("row_count", 0)

    delta     = cross.get("row_count_delta", abs(gl_rows - sub_rows))
    delta_pct = cross.get("row_count_delta_pct", 0.0)

    gl_amount = gl.get("numeric_distributions", {}).get("amount", {})
    gl_total  = gl_amount.get("sum")
    gl_mean   = gl_amount.get("mean")

    gl_null_pct  = {k: v for k, v in gl.get("null_percentages",  {}).items() if v > 0}
    sub_null_pct = {k: v for k, v in sub.get("null_percentages", {}).items() if v > 0}

    gl_dates = gl.get("date_ranges", {}).get("transaction_date", {})
    date_min = gl_dates.get("min", "N/A")
    date_max = gl_dates.get("max", "N/A")

    gl_entities  = gl.get("entity_distribution", {})
    entity_count = len(gl_entities)
    gl_dupes     = gl.get("duplicate_row_count", 0)
    sub_dupes    = sub.get("duplicate_row_count", 0)

    parts: list[str] = [
        f"Profiling complete. GL: {gl_rows:,} records | Subledger: {sub_rows:,} records | "
        f"Chart of Accounts: {coa_rows:,} accounts."
    ]

    if delta == 0:
        parts.append("GL and Subledger row counts are equal — full coverage expected.")
    else:
        parts.append(f"Row count delta: {delta:,} ({delta_pct:.2f}%) between GL and Subledger.")

    parts.append(f"GL transaction window: {date_min} to {date_max}.")

    if gl_total is not None:
        parts.append(
            f"Total GL transaction volume: ${gl_total:,.2f} (mean: ${gl_mean:,.2f} per record)."
        )

    if gl_entities:
        top_entities = sorted(gl_entities.items(), key=lambda x: -x[1])[:3]
        entity_str   = ", ".join(f"{e} ({n:,})" for e, n in top_entities)
        parts.append(
            f"{entity_count} distinct {'entity' if entity_count == 1 else 'entities'} in GL: {entity_str}."
        )

    if gl_null_pct:
        null_detail = ", ".join(f"{c} ({p:.1f}%)" for c, p in gl_null_pct.items())
        parts.append(f"GL nulls detected: {null_detail}.")
    else:
        parts.append("No null values detected in GL.")

    if sub_null_pct:
        null_detail = ", ".join(f"{c} ({p:.1f}%)" for c, p in sub_null_pct.items())
        parts.append(f"Subledger nulls detected: {null_detail}.")

    if gl_dupes > 0:
        parts.append(f"WARNING: {gl_dupes:,} exact duplicate row(s) detected in GL.")
    if sub_dupes > 0:
        parts.append(f"WARNING: {sub_dupes:,} exact duplicate row(s) detected in Subledger.")

    return " ".join(parts)


_SYSTEM_PROMPT = (
    "You are a financial data quality analyst. "
    "You receive profiling metrics from a reconciliation engine and write a concise, "
    "professional narrative summary (3-5 sentences) for a finance team. "
    "Highlight key statistics, any data quality concerns (nulls, duplicates, row-count gaps), "
    "and the overall readiness of the data for reconciliation. "
    "Do not use bullet points or markdown. Return plain text only."
)


def _metrics_summary_for_prompt(metrics: Dict[str, Any]) -> str:
    """Condense metrics into a compact JSON string for the prompt."""
    files = metrics.get("files", {})
    cross = metrics.get("cross_file", {})
    gl    = files.get("gl", {})
    sub   = files.get("subledger", {})

    compact = {
        "gl_rows":            gl.get("row_count", 0),
        "sub_rows":           sub.get("row_count", 0),
        "row_delta":          cross.get("row_count_delta", 0),
        "row_delta_pct":      cross.get("row_count_delta_pct", 0),
        "gl_date_range":      gl.get("date_ranges", {}).get("transaction_date", {}),
        "gl_amount":          gl.get("numeric_distributions", {}).get("amount", {}),
        "gl_nulls":           {k: v for k, v in gl.get("null_percentages", {}).items() if v > 0},
        "sub_nulls":          {k: v for k, v in sub.get("null_percentages", {}).items() if v > 0},
        "gl_duplicates":      gl.get("duplicate_row_count", 0),
        "sub_duplicates":     sub.get("duplicate_row_count", 0),
        "gl_entities":        gl.get("entity_distribution", {}),
        "gl_unique_vendors":  gl.get("unique_vendor_count", 0),
        "sub_unique_vendors": sub.get("unique_vendor_count", 0),
    }
    return json.dumps(compact)


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def generate_narrative(metrics: Dict[str, Any]) -> str:
    """
    Generate a human-readable profiling summary.

    Tries OpenAI first; falls back silently to the deterministic
    template if OPENAI_API_KEY is not set or the API call fails.

    Returns a single string suitable for embedding in an API response or report.
    """
    try:
        from src.llm.openai_client import OpenAIClient  # lazy import
        client = OpenAIClient()
        user_prompt = (
            "Here are the data profiling metrics for a reconciliation job:\n\n"
            f"{_metrics_summary_for_prompt(metrics)}\n\n"
            "Write a concise narrative summary (3-5 sentences) for the finance team."
        )
        text = client.generate_text(_SYSTEM_PROMPT, user_prompt, temperature=0, max_tokens=512)
        if text:
            return text
    except Exception:
        pass  # API key missing, network error, or any other issue — use fallback

    return _deterministic_narrative(metrics)
