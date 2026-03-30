"""
Column Mapping Service — Phase 1.5: files_loaded → column_mapping_complete

Responsibilities:
  1. analyze_columns()       — AI-driven column role detection (read-only, no state change)
  2. confirm_column_mapping() — Validates and persists the confirmed column map,
                                then advances state to column_mapping_complete

Architecture notes:
- analyze_columns is purely advisory: it returns suggestions without touching runtime.
- confirm_column_mapping validates that the mapped column names exist in the uploaded
  DataFrames and that required roles (id, vendor, amount) are assigned on both sides.
- entity and currency are optional; if entity is None on either side, entity blocking
  is skipped in downstream matching services.
"""

import json
import logging
from typing import Any, Dict, List, Optional

import pandas as pd

import src.core.runtime_manager as rm
from src.core.state_machine import ReconciliationState
from src.llm.openai_client import OpenAIClient
from src.schemas.column_mapping import (
    AnalyzeColumnsResponse,
    ColumnMapConfig,
    ColumnRole,
    ColumnSuggestion,
    SideColumnMap,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_REQUIRED_ROLES = {"id", "vendor", "amount"}      # both sides must have these
_SAMPLE_ROWS     = 5                               # rows sent to AI as examples
_MAX_CARDINALITY = 20                              # max unique values shown for low-cardinality cols

_SYSTEM_PROMPT = """\
You are a financial data analyst. Analyze column metadata from two reconciliation files \
and identify the semantic role of each column. Return structured JSON only — no prose, \
no markdown fences.

Valid roles: "id", "vendor", "amount", "date", "entity", "currency", "ignore"
- id:       unique row identifier
- vendor:   vendor or payee name
- amount:   monetary transaction amount
- date:     transaction or posting date
- entity:   company, division, business unit, or legal entity code
- currency: ISO currency code
- ignore:   column not relevant for reconciliation

For each column return:
  detected_role  — one of the valid roles above
  confidence     — float 0.0–1.0 (your certainty about this role assignment)

Also return a brief "analysis_narrative" (2–4 sentences) about overall data characteristics, \
data quality issues noticed, and any anomalies.

Response schema (strict JSON):
{
  "side_a": [
    {"column_name": "...", "detected_role": "...", "confidence": 0.0}
  ],
  "side_b": [
    {"column_name": "...", "detected_role": "...", "confidence": 0.0}
  ],
  "analysis_narrative": "..."
}
"""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _build_column_metadata(df: pd.DataFrame, side_label: str) -> str:
    """
    Build a compact string describing each column's dtype, cardinality, and sample values.
    Raw row data is never included — only aggregated metadata.
    """
    lines = [f"File: {side_label}"]
    for col in df.columns:
        series   = df[col].dropna()
        dtype    = str(df[col].dtype)
        n_unique = int(series.nunique())
        null_pct = round(df[col].isna().mean() * 100, 1)

        if n_unique <= _MAX_CARDINALITY:
            samples = [str(v) for v in series.unique()[:_SAMPLE_ROWS]]
        else:
            samples = [str(v) for v in series.head(_SAMPLE_ROWS).tolist()]

        lines.append(
            f"  {col}: dtype={dtype}, unique_values={n_unique}, "
            f"null_pct={null_pct}%, samples={samples}"
        )
    return "\n".join(lines)


def _parse_suggestions(raw: List[Dict[str, Any]]) -> List[ColumnSuggestion]:
    suggestions = []
    for item in raw:
        try:
            role = ColumnRole(item.get("detected_role", "ignore"))
        except ValueError:
            role = ColumnRole.IGNORE
        suggestions.append(ColumnSuggestion(
            column_name=item.get("column_name", ""),
            detected_role=role,
            confidence=float(item.get("confidence", 0.0)),
            sample_values=[],
        ))
    return suggestions


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def analyze_columns(session_id: str) -> AnalyzeColumnsResponse:
    """
    Analyze column roles in the uploaded files using AI.

    Read-only — does NOT modify runtime or advance state.
    Requires state: files_loaded
    """
    runtime     = rm.get_runtime(session_id)
    current     = rm.get_current_state(session_id)
    gl_df       = runtime["raw_data"].get("gl")
    sub_df      = runtime["raw_data"].get("subledger")
    column_map  = runtime["config"].get("column_map", {})

    side_a_label = column_map.get("side_a_label", "GL")
    side_b_label = column_map.get("side_b_label", "Subledger")

    if gl_df is None or sub_df is None:
        raise ValueError("Files must be uploaded before column analysis.")

    meta_a = _build_column_metadata(gl_df, side_a_label)
    meta_b = _build_column_metadata(sub_df, side_b_label)

    user_prompt = (
        f"Please analyze these two reconciliation files and identify the role of each column.\n\n"
        f"{meta_a}\n\n{meta_b}"
    )

    try:
        client   = OpenAIClient()
        response = client.generate_json(_SYSTEM_PROMPT, user_prompt, temperature=0)
    except Exception as exc:
        logger.warning("Column analysis AI call failed: %s. Returning empty suggestions.", exc)
        response = {"side_a": [], "side_b": [], "analysis_narrative": "AI analysis unavailable."}

    side_a_raw = response.get("side_a", [])
    side_b_raw = response.get("side_b", [])

    # Merge AI role suggestions with actual sample values from the DataFrame
    def _attach_samples(suggestions: List[ColumnSuggestion], df: pd.DataFrame) -> List[ColumnSuggestion]:
        for s in suggestions:
            if s.column_name in df.columns:
                s.sample_values = [
                    str(v) for v in df[s.column_name].dropna().head(_SAMPLE_ROWS).tolist()
                ]
        return suggestions

    side_a_suggestions = _attach_samples(_parse_suggestions(side_a_raw), gl_df)
    side_b_suggestions = _attach_samples(_parse_suggestions(side_b_raw), sub_df)

    # Fill any columns the AI missed
    ai_a_cols = {s.column_name for s in side_a_suggestions}
    for col in gl_df.columns:
        if col not in ai_a_cols:
            side_a_suggestions.append(ColumnSuggestion(
                column_name=col, detected_role=ColumnRole.IGNORE, confidence=0.0,
                sample_values=[str(v) for v in gl_df[col].dropna().head(_SAMPLE_ROWS).tolist()],
            ))

    ai_b_cols = {s.column_name for s in side_b_suggestions}
    for col in sub_df.columns:
        if col not in ai_b_cols:
            side_b_suggestions.append(ColumnSuggestion(
                column_name=col, detected_role=ColumnRole.IGNORE, confidence=0.0,
                sample_values=[str(v) for v in sub_df[col].dropna().head(_SAMPLE_ROWS).tolist()],
            ))

    return AnalyzeColumnsResponse(
        session_id=session_id,
        state=current.value,
        side_a_label=side_a_label,
        side_b_label=side_b_label,
        side_a_suggestions=side_a_suggestions,
        side_b_suggestions=side_b_suggestions,
        analysis_narrative=response.get("analysis_narrative", ""),
    )


def confirm_column_mapping(session_id: str, column_map: ColumnMapConfig) -> None:
    """
    Validate and persist the user-confirmed column mapping, then advance state
    to column_mapping_complete.

    Validation rules:
    - id, vendor, and amount must be assigned on both sides (entity/currency optional)
    - All mapped column names must actually exist in the uploaded DataFrames
    """
    runtime = rm.get_runtime(session_id)
    gl_df   = runtime["raw_data"].get("gl")
    sub_df  = runtime["raw_data"].get("subledger")

    if gl_df is None or sub_df is None:
        raise ValueError("Files must be uploaded before confirming column mapping.")

    gl_cols  = set(gl_df.columns)
    sub_cols = set(sub_df.columns)

    # Validate required roles on side_a
    _validate_side(column_map.side_a, gl_cols, "side_a")
    # Validate required roles on side_b
    _validate_side(column_map.side_b, sub_cols, "side_b")

    rm.write_column_map(session_id, column_map.model_dump())
    rm.advance_state(
        session_id,
        ReconciliationState.COLUMN_MAPPING_COMPLETE,
        triggered_by="confirm_column_mapping",
    )


def _validate_side(side: SideColumnMap, available_cols: set, side_name: str) -> None:
    """Validate required roles are present and all mapped column names exist in the DataFrame."""
    mapping = side.model_dump()

    for role in _REQUIRED_ROLES:
        if mapping.get(role) is None:
            raise ValueError(
                f"{side_name}: role '{role}' is required but not assigned. "
                f"Please map a column to this role."
            )

    for role, col_name in mapping.items():
        if col_name is not None and col_name not in available_cols:
            raise ValueError(
                f"{side_name}: column '{col_name}' (mapped to role '{role}') "
                f"does not exist in the uploaded file. "
                f"Available columns: {sorted(available_cols)}"
            )
