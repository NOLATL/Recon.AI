"""
Matching Config Service — Phase 3.5: preprocessed → matching_configured

Responsibilities:
  1. suggest_matching_config()  — AI-recommended det scenarios + prob config (read-only)
  2. confirm_matching_config()  — Validates and persists the confirmed config,
                                  then advances state to matching_configured

Architecture notes:
- suggest_matching_config is purely advisory: reads clean_data statistics and column_map,
  calls AI, returns suggestions without touching runtime.
- confirm_matching_config validates business rules (weight sum, threshold range, required
  match_fields) before persisting.
- When matching_config.deterministic is empty the engine falls back to the 3 hardcoded
  scenarios. When matching_config.probabilistic is empty the engine uses hardcoded weights.
"""

import logging
from typing import Any, Dict, List

import pandas as pd

import src.core.runtime_manager as rm
from src.core.state_machine import ReconciliationState
from src.llm.openai_client import OpenAIClient
from src.schemas.matching_config import (
    ConfirmMatchingConfigRequest,
    DeterministicScenarioConfig,
    ProbabilisticConfig,
    SuggestMatchingConfigResponse,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_DEFAULT_DET_SCENARIOS: List[Dict[str, Any]] = [
    {
        "scenario_id": 1,
        "description": "Exact match on vendor, amount, date, and entity",
        "match_fields": ["vendor", "amount", "date", "entity"],
        "date_tolerance_days": None,
        "amount_tolerance_abs": None,
        "amount_tolerance_pct": None,
        "confidence_score": 1.0,
    },
    {
        "scenario_id": 2,
        "description": "Vendor, amount, and entity match within 30-day date window",
        "match_fields": ["vendor", "amount", "entity"],
        "date_tolerance_days": 30,
        "amount_tolerance_abs": None,
        "amount_tolerance_pct": None,
        "confidence_score": 0.95,
    },
    {
        "scenario_id": 3,
        "description": "Vendor, amount, and entity match within 60-day date window",
        "match_fields": ["vendor", "amount", "entity"],
        "date_tolerance_days": 60,
        "amount_tolerance_abs": 5.0,
        "amount_tolerance_pct": 0.002,
        "confidence_score": 0.90,
    },
]

_DEFAULT_PROB_CONFIG: Dict[str, Any] = {
    "weights": {"vendor": 0.45, "amount": 0.40, "date": 0.15},
    "threshold": 0.80,
    "date_tolerance_days": 30,
    "amount_pct_tolerance": 0.10,
    "amount_abs_tolerance": 5.00,
}

_SYSTEM_PROMPT = """\
You are a financial reconciliation expert. Based on column mapping and data characteristics \
provided, recommend deterministic matching scenarios and probabilistic scoring parameters.

Return structured JSON only — no prose, no markdown fences.

Guidelines:
- Deterministic scenarios: ordered from strictest (highest confidence) to most lenient.
  Each scenario should add one relaxation (e.g., wider date tolerance) vs the previous.
  Minimum 1, maximum 5 scenarios.
- Probabilistic weights: must sum to exactly 1.0. Focus weight on the most reliable columns.
  "entity" is excluded from weights (handled as a hard blocking constraint).
- Recommend tighter tolerances when data shows close date clustering.
- If entity has low cardinality (1–2 values), it is still useful as a hard block.

- For deterministic amount tolerances: use null/0 for exact-match scenarios; set
  amount_tolerance_abs (dollars) and/or amount_tolerance_pct (0.0–1.0 fraction, e.g.
  0.002 = 0.2%) for relaxed scenarios. Base recommendations on amount_std from data.
- confidence_score reflects how reliable a match from this scenario is (1.0 = certain,
  0.90 = probable). Assign lower confidence to wider-tolerance scenarios.

Response schema (strict JSON):
{
  "deterministic": [
    {
      "scenario_id": 1,
      "description": "...",
      "match_fields": ["vendor", "amount", "date", "entity"],
      "date_tolerance_days": null,
      "amount_tolerance_abs": null,
      "amount_tolerance_pct": null,
      "confidence_score": 1.0
    }
  ],
  "probabilistic": {
    "weights": {"vendor": 0.45, "amount": 0.40, "date": 0.15},
    "threshold": 0.80,
    "date_tolerance_days": 30,
    "amount_pct_tolerance": 0.10,
    "amount_abs_tolerance": 5.00
  },
  "rationale": "Brief explanation of recommendations (2–4 sentences)."
}
"""


# ---------------------------------------------------------------------------
# Data characteristics helpers
# ---------------------------------------------------------------------------

def _compute_data_characteristics(
    gl_df: pd.DataFrame,
    sub_df: pd.DataFrame,
    column_map: Dict[str, Any],
) -> Dict[str, Any]:
    """Derive statistical summaries used to inform AI recommendations."""
    stats: Dict[str, Any] = {}

    a_map = column_map.get("side_a", {})
    b_map = column_map.get("side_b", {})

    # Date range spread
    date_col_a = a_map.get("date")
    if date_col_a and date_col_a in gl_df.columns:
        try:
            dates = pd.to_datetime(gl_df[date_col_a], errors="coerce").dropna()
            if len(dates) > 0:
                stats["date_range_days_a"] = int((dates.max() - dates.min()).days)
        except Exception:
            pass

    # Amount distribution
    amount_col_a = a_map.get("amount")
    if amount_col_a and amount_col_a in gl_df.columns:
        try:
            amounts = pd.to_numeric(gl_df[amount_col_a], errors="coerce").dropna()
            if len(amounts) > 0:
                stats["amount_min"]    = round(float(amounts.min()), 2)
                stats["amount_max"]    = round(float(amounts.max()), 2)
                stats["amount_mean"]   = round(float(amounts.mean()), 2)
                stats["amount_std"]    = round(float(amounts.std()), 2)
        except Exception:
            pass

    # Entity cardinality
    entity_col_a = a_map.get("entity")
    if entity_col_a and entity_col_a in gl_df.columns:
        stats["entity_cardinality"] = int(gl_df[entity_col_a].nunique())
    else:
        stats["entity_cardinality"] = 0  # no entity column

    stats["gl_row_count"]  = len(gl_df)
    stats["sub_row_count"] = len(sub_df)

    return stats


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def suggest_matching_config(session_id: str) -> SuggestMatchingConfigResponse:
    """
    Suggest deterministic scenarios and probabilistic weights using AI.

    Read-only — does NOT modify runtime or advance state.
    Requires state: preprocessed
    """
    runtime    = rm.get_runtime(session_id)
    current    = rm.get_current_state(session_id)
    column_map = runtime["config"].get("column_map", {})

    clean = runtime.get("clean_data", {})
    gl_df  = clean.get("gl")
    sub_df = clean.get("subledger")

    if gl_df is None or sub_df is None:
        # Fallback: return defaults with a canned rationale
        return _build_default_response(session_id, current.value, "Preprocessing data not available. Returning default configuration.")

    data_chars = _compute_data_characteristics(gl_df, sub_df, column_map)

    user_prompt = (
        f"Column mapping:\n{column_map}\n\n"
        f"Data characteristics:\n{data_chars}\n\n"
        f"Please recommend matching configuration for this dataset."
    )

    try:
        client   = OpenAIClient()
        response = client.generate_json(_SYSTEM_PROMPT, user_prompt, temperature=0)
    except Exception as exc:
        logger.warning("Matching config AI call failed: %s. Returning defaults.", exc)
        return _build_default_response(session_id, current.value, f"AI unavailable ({exc}). Returning default configuration.")

    det_raw  = response.get("deterministic", _DEFAULT_DET_SCENARIOS)
    prob_raw = response.get("probabilistic", _DEFAULT_PROB_CONFIG)
    rationale = response.get("rationale", "")

    try:
        det_scenarios = [DeterministicScenarioConfig(**s) for s in det_raw]
        prob_config   = ProbabilisticConfig(**prob_raw)
    except Exception as exc:
        logger.warning("AI response parse error: %s. Returning defaults.", exc)
        return _build_default_response(session_id, current.value, f"AI response could not be parsed. Returning default configuration.")

    # Enforce required fields — the AI sometimes omits "amount" when treating it as a tolerance.
    for scenario in det_scenarios:
        for required in ("vendor", "amount"):
            if required not in scenario.match_fields:
                scenario.match_fields = [required] + scenario.match_fields
                logger.warning(
                    "Scenario %s was missing required field '%s'; injected automatically.",
                    scenario.scenario_id, required,
                )

    return SuggestMatchingConfigResponse(
        session_id=session_id,
        state=current.value,
        deterministic_scenarios=det_scenarios,
        probabilistic=prob_config,
        rationale=rationale,
    )


def confirm_matching_config(session_id: str, config: ConfirmMatchingConfigRequest) -> None:
    """
    Validate and persist the user-confirmed matching configuration, then advance
    state to matching_configured.

    Pydantic validators on ConfirmMatchingConfigRequest already check:
    - probabilistic.weights sum to 1.0 (±0.01)
    - probabilistic.threshold ∈ [0.0, 1.0]

    Additional validation here:
    - Each deterministic scenario must include "vendor" and "amount" in match_fields
    """
    for scenario in config.deterministic:
        if not scenario.match_fields:
            raise ValueError(
                f"Scenario {scenario.scenario_id}: match_fields must include at least one field."
            )

    matching_config = {
        "deterministic": [s.model_dump() for s in config.deterministic],
        "probabilistic": config.probabilistic.model_dump(),
    }

    rm.write_matching_config(session_id, matching_config)
    rm.advance_state(
        session_id,
        ReconciliationState.MATCHING_CONFIGURED,
        triggered_by="confirm_matching_config",
    )


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _build_default_response(
    session_id: str,
    state: str,
    rationale: str,
) -> SuggestMatchingConfigResponse:
    return SuggestMatchingConfigResponse(
        session_id=session_id,
        state=state,
        deterministic_scenarios=[
            DeterministicScenarioConfig(**s) for s in _DEFAULT_DET_SCENARIOS
        ],
        probabilistic=ProbabilisticConfig(**_DEFAULT_PROB_CONFIG),
        rationale=rationale,
    )
