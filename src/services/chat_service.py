"""
Chat Service — General-purpose data exploration chat

Available in any session state ≥ files_loaded.

The chat service gives users a conversational interface to explore their
reconciliation data and modify the matching plan via natural language.

The AI always returns JSON: {"reply": "...", "config_update": null | {...}}
Conversation history is passed in by the caller (stateless on the backend).
The frontend is responsible for storing and replaying the history.
"""

import json
import logging
from typing import Any, Dict, List, Optional

import pandas as pd

import src.core.runtime_manager as rm
from src.llm.openai_client import OpenAIClient
from src.schemas.chat import ChatRequest, ChatResponse, ChatMessage, MatchingConfigUpdate

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# System prompt
# ---------------------------------------------------------------------------

_SYSTEM_PROMPT_TEMPLATE = """\
You are a financial reconciliation assistant. You help users understand their data \
and can update the matching plan when asked.

Current session state: {state}

{file_summary}

{column_roles}

{matching_config}

{matching_progress}

{data_context}

RESPONSE FORMAT — you MUST always return valid JSON in exactly this structure:
{
  "reply": "Your conversational response here",
  "config_update": null
}

OR when the user asks you to change the matching plan:
{
  "reply": "I've updated the matching configuration as requested...",
  "config_update": {
    "deterministic": [
      {
        "scenario_id": 1,
        "description": "...",
        "match_fields": ["vendor", "amount", "date", "entity"],
        "date_tolerance_days": null,
        "confidence_score": 1.0
      }
    ],
    "probabilistic": {
      "weights": {"vendor": 0.45, "amount": 0.40, "date": 0.15},
      "threshold": 0.80,
      "date_tolerance_days": 30,
      "amount_pct_tolerance": 0.10,
      "amount_abs_tolerance": 5.00
    }
  }
}

RULES:
- match_fields must always include both "vendor" and "amount"
- weights must sum to exactly 1.0 (use up to 4 decimal places to ensure this)
- For config changes, return the COMPLETE updated config — not just the changed fields
- date_tolerance_days: use null for exact date match, or an integer for tolerance in days
- confidence_score: 1.0 for exact match, decrease for each relaxation (min 0.80)
- Set config_update to null for data questions; only set it when plan changes are requested
- Keep replies concise (2–4 sentences for data questions, 1–2 for config confirmations)
"""


# ---------------------------------------------------------------------------
# Context builders
# ---------------------------------------------------------------------------

def _build_file_summary(runtime: dict) -> str:
    column_map = runtime["config"].get("column_map", {})
    raw_data   = runtime.get("raw_data", {})
    clean_data = runtime.get("clean_data", {})

    side_a_label = column_map.get("side_a_label", "GL")
    side_b_label = column_map.get("side_b_label", "Subledger")

    gl_df  = clean_data.get("gl")  if clean_data.get("gl")  is not None else raw_data.get("gl")
    sub_df = clean_data.get("subledger") if clean_data.get("subledger") is not None else raw_data.get("subledger")

    lines = []
    if gl_df is not None:
        lines.append(f"{side_a_label}: {len(gl_df)} rows, columns: {list(gl_df.columns)}")
        summary = _summarize_df(gl_df, side_a_label, column_map.get("side_a", {}))
        if summary:
            lines.append(summary)

    if sub_df is not None:
        lines.append(f"{side_b_label}: {len(sub_df)} rows, columns: {list(sub_df.columns)}")
        summary = _summarize_df(sub_df, side_b_label, column_map.get("side_b", {}))
        if summary:
            lines.append(summary)

    return "\n".join(lines) if lines else "No file data available yet."


def _summarize_df(df: pd.DataFrame, label: str, role_map: Dict[str, Optional[str]]) -> str:
    parts = []

    amount_col = role_map.get("amount")
    if amount_col and amount_col in df.columns:
        amounts = pd.to_numeric(df[amount_col], errors="coerce").dropna()
        if len(amounts) > 0:
            parts.append(
                f"{label} amounts: min={amounts.min():.2f}, max={amounts.max():.2f}, "
                f"total={amounts.sum():.2f}, mean={amounts.mean():.2f}"
            )

    date_col = role_map.get("date")
    if date_col and date_col in df.columns:
        dates = pd.to_datetime(df[date_col], errors="coerce").dropna()
        if len(dates) > 0:
            parts.append(f"{label} date range: {dates.min().date()} to {dates.max().date()}")

    vendor_col = role_map.get("vendor")
    if vendor_col and vendor_col in df.columns:
        vendor_counts = df[vendor_col].dropna().value_counts()
        top = vendor_counts.head(15)
        vendor_list = [f"{v} ({c})" for v, c in top.items()]
        parts.append(
            f"{label} vendors ({len(vendor_counts)} unique, showing top {len(top)}): {vendor_list}"
        )

    entity_col = role_map.get("entity")
    if entity_col and entity_col in df.columns:
        entities = df[entity_col].dropna().unique()
        parts.append(f"{label} entities ({len(entities)}): {list(entities[:5])}")

    return "  " + " | ".join(parts) if parts else ""


def _build_column_roles(runtime: dict) -> str:
    column_map = runtime["config"].get("column_map", {})
    if not column_map:
        return ""
    side_a_label = column_map.get("side_a_label", "GL")
    side_b_label = column_map.get("side_b_label", "Subledger")
    lines = ["Column roles:"]
    for side_key, side_label in [("side_a", side_a_label), ("side_b", side_b_label)]:
        side = column_map.get(side_key, {})
        role_list = [f"{role}={col}" for role, col in side.items() if col]
        if role_list:
            lines.append(f"  {side_label}: {', '.join(role_list)}")
    return "\n".join(lines)


def _build_matching_config_section(runtime: dict, matching_context: Optional[Dict[str, Any]]) -> str:
    """Build a description of the current matching config for the system prompt."""
    # Prefer matching_context (proposed, not-yet-confirmed config sent by frontend)
    config_source = matching_context or runtime["config"].get("matching_config")
    if not config_source:
        return "No matching configuration set yet."

    det = config_source.get("deterministic", [])
    prob = config_source.get("probabilistic", {})

    lines = ["Current matching plan:"]
    lines.append(f"  Deterministic scenarios ({len(det)} total):")
    for s in det:
        tol = f", ±{s.get('date_tolerance_days')}d" if s.get("date_tolerance_days") else ""
        lines.append(f"    Scenario {s.get('scenario_id')}: {s.get('description')} "
                     f"[fields: {s.get('match_fields')}{tol}, conf={s.get('confidence_score')}]")
    if prob:
        weights = prob.get("weights", {})
        lines.append(f"  Probabilistic weights: {weights} (sum={sum(weights.values()):.2f})")
        lines.append(f"  Threshold: {prob.get('threshold')}, "
                     f"date tolerance: {prob.get('date_tolerance_days')}d, "
                     f"amount %: {prob.get('amount_pct_tolerance')}")
    return "\n".join(lines)


_DATA_CONTEXT_ROW_LIMIT = 500  # rows per side; keeps token cost reasonable


def _build_data_context(runtime: dict) -> str:
    """Include actual CSV rows so the AI can answer precise data questions."""
    column_map = runtime["config"].get("column_map", {})
    raw_data   = runtime.get("raw_data", {})
    clean_data = runtime.get("clean_data", {})

    side_a_label = column_map.get("side_a_label", "GL")
    side_b_label = column_map.get("side_b_label", "Subledger")

    gl_df  = clean_data.get("gl")  if clean_data.get("gl")  is not None else raw_data.get("gl")
    sub_df = clean_data.get("subledger") if clean_data.get("subledger") is not None else raw_data.get("subledger")

    parts = []
    for label, df in [(side_a_label, gl_df), (side_b_label, sub_df)]:
        if df is None:
            continue
        total = len(df)
        sample = df.head(_DATA_CONTEXT_ROW_LIMIT)
        note = f" (showing first {_DATA_CONTEXT_ROW_LIMIT} of {total})" if total > _DATA_CONTEXT_ROW_LIMIT else ""
        parts.append(f"{label} DATA{note}:\n{sample.to_csv(index=False)}")

    return "\n\n".join(parts) if parts else ""


def _build_matching_progress(runtime: dict) -> str:
    matching = runtime.get("matching", {})
    det_count  = len(matching.get("deterministic", []))
    prob_count = len(matching.get("probabilistic", []))
    ai_count   = len(matching.get("ai_suggested", []))
    if not (det_count or prob_count or ai_count):
        return ""
    return f"Matching progress: {det_count} deterministic, {prob_count} probabilistic, {ai_count} AI matches"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def chat_message(session_id: str, request: ChatRequest) -> ChatResponse:
    """
    Handle a general-purpose chat message about the session's data.

    The AI always returns JSON {reply, config_update}.
    config_update is non-null only when the user asks to change the matching plan.

    Stateless on the backend — conversation history is passed in by the caller.
    """
    try:
        runtime = rm.get_runtime(session_id)
        state   = runtime.get("current_state", "unknown")

        file_summary      = _build_file_summary(runtime)
        column_roles      = _build_column_roles(runtime)
        matching_config   = _build_matching_config_section(runtime, request.matching_context)
        matching_progress = _build_matching_progress(runtime)
        data_context      = _build_data_context(runtime)

        # Build prompt by replacement rather than .format() — avoids KeyError when
        # substituted values contain literal { } (e.g. dict/list representations).
        system_prompt = (
            _SYSTEM_PROMPT_TEMPLATE
            .replace("{state}", str(state))
            .replace("{file_summary}", str(file_summary))
            .replace("{column_roles}", str(column_roles))
            .replace("{matching_config}", str(matching_config))
            .replace("{matching_progress}", str(matching_progress))
            .replace("{data_context}", str(data_context))
        )

        messages = [
            {"role": msg.role, "content": msg.content}
            for msg in request.conversation_history
        ]
        messages.append({"role": "user", "content": request.message})

        client     = OpenAIClient()
        result     = client.generate_with_history_json(system_prompt, messages, temperature=0.4)
        reply      = result.get("reply", "")
        raw_update = result.get("config_update")
    except Exception as exc:
        logger.error("Chat failed for session %s: %s", session_id, exc, exc_info=True)
        return ChatResponse(
            session_id=session_id,
            reply=f"Sorry, I ran into an error: {exc}",
            config_update=None,
        )

    config_update: Optional[MatchingConfigUpdate] = None
    if raw_update and isinstance(raw_update, dict):
        try:
            config_update = MatchingConfigUpdate(
                deterministic=raw_update.get("deterministic"),
                probabilistic=raw_update.get("probabilistic"),
            )
            # Enforce vendor+amount in every deterministic scenario
            if config_update.deterministic:
                for s in config_update.deterministic:
                    for req in ("vendor", "amount"):
                        if req not in s.get("match_fields", []):
                            s["match_fields"] = [req] + s.get("match_fields", [])
        except Exception as exc:
            logger.warning("Failed to parse config_update from AI: %s", exc)
            config_update = None

    return ChatResponse(
        session_id=session_id,
        reply=reply,
        config_update=config_update,
    )
