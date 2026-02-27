"""
Narrative service — deterministic template stub.

Returns a rule-based summary of profiling metrics.
Replace generate_narrative() with an LLM call (Anthropic / OpenAI) in a later phase.
The stub signature and return type are intentionally identical to the future
AI version so the caller (profiling_routes.py) requires no changes.
"""

from typing import Any, Dict


def generate_narrative(metrics: Dict[str, Any]) -> str:
    """
    Build a human-readable profiling summary from computed metrics.

    Deterministic — same metrics always produce the same narrative.
    No external calls, no randomness.

    Returns a single string suitable for embedding in an API response or report.
    """
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

    # --- GL amount summary ---
    gl_amount = gl.get("numeric_distributions", {}).get("amount", {})
    gl_total  = gl_amount.get("sum")
    gl_mean   = gl_amount.get("mean")

    # --- Null detection ---
    gl_null_pct  = {k: v for k, v in gl.get("null_percentages",  {}).items() if v > 0}
    sub_null_pct = {k: v for k, v in sub.get("null_percentages", {}).items() if v > 0}

    # --- GL date range ---
    gl_dates     = gl.get("date_ranges",  {}).get("transaction_date", {})
    date_min     = gl_dates.get("min", "N/A")
    date_max     = gl_dates.get("max", "N/A")

    # --- Entity coverage ---
    gl_entities  = gl.get("entity_distribution",  {})
    entity_count = len(gl_entities)

    # --- Duplicate flags ---
    gl_dupes  = gl.get("duplicate_row_count",  0)
    sub_dupes = sub.get("duplicate_row_count", 0)

    parts: list[str] = []

    # Volume
    parts.append(
        f"Profiling complete. "
        f"GL: {gl_rows:,} records | "
        f"Subledger: {sub_rows:,} records | "
        f"Chart of Accounts: {coa_rows:,} accounts."
    )

    # Coverage delta
    if delta == 0:
        parts.append("GL and Subledger row counts are equal — full coverage expected.")
    else:
        parts.append(
            f"Row count delta: {delta:,} ({delta_pct:.2f}%) between GL and Subledger."
        )

    # Transaction window
    parts.append(f"GL transaction window: {date_min} to {date_max}.")

    # Amount summary
    if gl_total is not None:
        parts.append(
            f"Total GL transaction volume: ${gl_total:,.2f} "
            f"(mean: ${gl_mean:,.2f} per record)."
        )

    # Entity breakdown
    if gl_entities:
        top_entities = sorted(gl_entities.items(), key=lambda x: -x[1])[:3]
        entity_str   = ", ".join(f"{e} ({n:,})" for e, n in top_entities)
        parts.append(
            f"{entity_count} distinct {'entity' if entity_count == 1 else 'entities'} in GL: {entity_str}."
        )

    # Null warnings
    if gl_null_pct:
        null_detail = ", ".join(f"{c} ({p:.1f}%)" for c, p in gl_null_pct.items())
        parts.append(f"GL nulls detected: {null_detail}.")
    else:
        parts.append("No null values detected in GL.")

    if sub_null_pct:
        null_detail = ", ".join(f"{c} ({p:.1f}%)" for c, p in sub_null_pct.items())
        parts.append(f"Subledger nulls detected: {null_detail}.")

    # Duplicate warnings
    if gl_dupes > 0:
        parts.append(f"WARNING: {gl_dupes:,} exact duplicate row(s) detected in GL.")
    if sub_dupes > 0:
        parts.append(f"WARNING: {sub_dupes:,} exact duplicate row(s) detected in Subledger.")

    parts.append("[AI narrative not yet enabled — deterministic stub output only]")

    return " ".join(parts)
