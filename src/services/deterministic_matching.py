"""
Deterministic Matching Service — Phase 4: preprocessed → deterministic_complete

Four ordered scenarios (each scenario operates only on records not consumed by prior ones):

  Scenario 1 — Strict 1:1
    Exact match on: Vendor_Normalized, amount (rounded to 2 dp), transaction_date, entity
    Confidence: 1.00 | grouping_type: "one_to_one"

  Scenario 2 — Vendor + Amount + Entity + narrow date tolerance
    Exact match on: Vendor_Normalized, amount (rounded to 2 dp), entity
    Date tolerance: abs(date_gl − date_sub) ≤ 30 days
    Confidence: 0.95 | grouping_type: "one_to_one"

  Scenario 3 — Vendor + Amount + Entity + wide date tolerance
    Exact match on: Vendor_Normalized, amount (rounded to 2 dp), entity
    Date tolerance: abs(date_gl − date_sub) ≤ 60 days
    Confidence: 0.90 | grouping_type: "one_to_one"

  N:M grouping (splits and accruals) is handled by the Probabilistic phase.

Architecture notes:
  - Pure function: run_deterministic_matching() has no side effects on the runtime.
  - Records are consumed greedily — scenario 1 removes matched IDs before scenario 2 runs.
  - Amount comparison uses round(..., 2) to avoid float precision drift.
  - transaction_date is normalised to YYYY-MM-DD strings before exact merge (scenario 1);
    date ordinals (days since epoch) are pre-computed per-pool before the cross-product
    merge in scenarios 2–3, so date arithmetic never runs on the merged cross-product.
  - Scenario 4 pre-filters combination candidates by amount (≤ target) and guards with
    a sum-feasibility check before entering the combinations loop.
  - Required columns:
      GL DataFrame:  gl_id, Vendor_Normalized, amount, transaction_date, entity
      Sub DataFrame: subledger_id, Vendor_Normalized, amount, transaction_date, entity
"""

import logging
import time
import uuid
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Set, Tuple

import pandas as pd

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DATE_TOLERANCE_NARROW: int = 30   # Scenario 2
DATE_TOLERANCE_WIDE:   int = 60   # Scenario 3
_EPOCH = pd.Timestamp("1970-01-01")

_SCENARIO_META: Dict[int, dict] = {
    1: {
        "description": "Strict 1:1: exact Vendor_Normalized, amount, date, entity",
        "confidence_score": 1.00,
    },
    2: {
        "description": "Vendor + Amount + Entity match with date tolerance ±30 days",
        "confidence_score": 0.95,
    },
    3: {
        "description": "Vendor + Amount + Entity match with date tolerance ±60 days",
        "confidence_score": 0.90,
    },
}


# ---------------------------------------------------------------------------
# Result dataclasses
# ---------------------------------------------------------------------------

@dataclass
class MatchRecord:
    """One deterministic match linking GL record(s) to Subledger record(s)."""
    match_id: str
    record_ids_A: List[str]         # GL gl_id values
    record_ids_B: List[str]         # Subledger subledger_id values
    scenario_id: int
    scenario_description: str
    confidence_score: float
    grouping_type: str              # "one_to_one" | "one_to_many" | "many_to_one"
    match_fields: List[str] = None              # role names used in this scenario
    date_tolerance_days: Optional[int] = None   # None/0 = exact date
    amount_tolerance_abs: Optional[float] = None
    amount_tolerance_pct: Optional[float] = None
    user_status: str = "auto_confirmed"
    override_flag: bool = False

    def __post_init__(self):
        if self.match_fields is None:
            self.match_fields = []

    def to_dict(self) -> dict:
        return {
            "match_id":              self.match_id,
            "record_ids_A":          self.record_ids_A,
            "record_ids_B":          self.record_ids_B,
            "scenario_id":           self.scenario_id,
            "scenario_description":  self.scenario_description,
            "confidence_score":      self.confidence_score,
            "grouping_type":         self.grouping_type,
            "match_fields":          self.match_fields,
            "date_tolerance_days":   self.date_tolerance_days,
            "amount_tolerance_abs":  self.amount_tolerance_abs,
            "amount_tolerance_pct":  self.amount_tolerance_pct,
            "user_status":           self.user_status,
            "override_flag":         self.override_flag,
        }


@dataclass
class DeterministicResult:
    """Full output of run_deterministic_matching()."""
    matches: List[MatchRecord]
    residual_gl: pd.DataFrame
    residual_sub: pd.DataFrame
    total_gl: int
    total_sub: int
    scenario_counts: Dict[int, int]     # {1: N, 2: N, 3: N, 4: N}

    @property
    def matched_gl(self) -> int:
        return self.total_gl - len(self.residual_gl)

    @property
    def matched_sub(self) -> int:
        return self.total_sub - len(self.residual_sub)

    def to_match_list(self) -> List[dict]:
        return [m.to_dict() for m in self.matches]


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------

def _normalise_amount(series: pd.Series) -> pd.Series:
    """Convert to float and round to 2 decimal places."""
    return pd.to_numeric(series, errors="coerce").round(2)


def _normalise_date_str(series: pd.Series) -> pd.Series:
    """Normalise to YYYY-MM-DD string for exact merge comparison."""
    return pd.to_datetime(series, errors="coerce").dt.strftime("%Y-%m-%d")


def _date_ordinals(series: pd.Series) -> pd.Series:
    """
    Convert a date series to integer days-since-epoch.

    Pre-computing on the individual pool (N rows) rather than on the merged
    cross-product (up to N×M rows) means date parsing runs once per record,
    not once per candidate pair.
    """
    return (pd.to_datetime(series, errors="coerce") - _EPOCH).dt.days


def _make_match_1to1(
    row: pd.Series,
    gl_id_col: str,
    sub_id_col: str,
    scenario_id: int,
) -> MatchRecord:
    return MatchRecord(
        match_id=str(uuid.uuid4()),
        record_ids_A=[str(row[gl_id_col])],
        record_ids_B=[str(row[sub_id_col])],
        scenario_id=scenario_id,
        scenario_description=_SCENARIO_META[scenario_id]["description"],
        confidence_score=_SCENARIO_META[scenario_id]["confidence_score"],
        grouping_type="one_to_one",
    )


def _filter_pool(df: pd.DataFrame, id_col: str, used_ids: Set[str]) -> pd.DataFrame:
    """Return rows of *df* whose *id_col* is not in *used_ids*. Safe for empty DataFrames."""
    if df.empty or id_col not in df.columns:
        return df
    return df[~df[id_col].astype(str).isin(used_ids)]


def _greedy_1to1(
    merged: pd.DataFrame,
    gl_id_col: str,
    sub_id_col: str,
    scenario_id: int,
    scenario_description: Optional[str] = None,
    confidence_score: Optional[float] = None,
    match_fields: Optional[List[str]] = None,
    date_tolerance_days: Optional[int] = None,
    amount_tolerance_abs: Optional[float] = None,
    amount_tolerance_pct: Optional[float] = None,
) -> Tuple[List[MatchRecord], Set[str], Set[str]]:
    """
    Walk merged rows in order, producing 1:1 matches; each ID used at most once.
    Returns (matches, used_gl_ids, used_sub_ids).
    """
    matches: List[MatchRecord] = []
    used_gl: Set[str] = set()
    used_sub: Set[str] = set()

    desc  = scenario_description or _SCENARIO_META.get(scenario_id, {}).get("description", f"Scenario {scenario_id}")
    score = confidence_score     or _SCENARIO_META.get(scenario_id, {}).get("confidence_score", 1.0)

    for _, row in merged.iterrows():
        gl_id  = str(row[gl_id_col])
        sub_id = str(row[sub_id_col])
        if gl_id not in used_gl and sub_id not in used_sub:
            used_gl.add(gl_id)
            used_sub.add(sub_id)
            matches.append(MatchRecord(
                match_id=str(uuid.uuid4()),
                record_ids_A=[gl_id],
                record_ids_B=[sub_id],
                scenario_id=scenario_id,
                scenario_description=desc,
                confidence_score=score,
                grouping_type="one_to_one",
                match_fields=list(match_fields) if match_fields else [],
                date_tolerance_days=date_tolerance_days,
                amount_tolerance_abs=amount_tolerance_abs,
                amount_tolerance_pct=amount_tolerance_pct,
            ))

    return matches, used_gl, used_sub


# Role → standardized column name (after _standardize_df has been applied)
_ROLE_TO_STD_COL: Dict[str, str] = {
    "vendor":   "Vendor_Normalized",
    "entity":   "entity",
    "currency": "currency",
    "id":       "gl_id",   # unusual but supported; note: sub side uses "subledger_id"
}


def _run_dynamic_scenario(
    gl_pool: pd.DataFrame,
    sub_pool: pd.DataFrame,
    config: Dict,
    scenario_id: int,
) -> Tuple[List[MatchRecord], Set[str], Set[str]]:
    """
    Execute a single user-configured deterministic scenario.

    config keys consumed:
        match_fields          list[str]  — role names to match on
        date_tolerance_days   int|None   — 0/None = exact date
        amount_tolerance_abs  float|None — 0/None = exact amount
        amount_tolerance_pct  float|None — 0/None = exact amount
        description           str
        confidence_score      float
    """
    if gl_pool.empty or sub_pool.empty:
        return [], set(), set()

    match_fields    = config.get("match_fields", [])
    date_tol        = int(config.get("date_tolerance_days") or 0)
    amount_abs_tol  = float(config.get("amount_tolerance_abs") or 0.0)
    amount_pct_tol  = float(config.get("amount_tolerance_pct") or 0.0)
    description     = config.get("description", f"Scenario {scenario_id}")
    conf_score      = float(config.get("confidence_score", 1.0))

    gl_s  = gl_pool.copy()
    sub_s = sub_pool.copy()

    # Build exact join keys
    exact_join_cols: List[str] = []
    for role in match_fields:
        if role in ("date", "amount"):
            continue   # handled separately below
        col = _ROLE_TO_STD_COL.get(role)
        if col and col in gl_s.columns and col in sub_s.columns:
            exact_join_cols.append(col)

    # Amount: exact key or post-merge tolerance filter
    use_exact_amount = "amount" in match_fields and amount_abs_tol == 0.0 and amount_pct_tol == 0.0
    use_tol_amount   = "amount" in match_fields and (amount_abs_tol > 0.0 or amount_pct_tol > 0.0)
    if use_exact_amount:
        gl_s["_ak"]  = _normalise_amount(gl_s["amount"])
        sub_s["_ak"] = _normalise_amount(sub_s["amount"])
        exact_join_cols.append("_ak")

    # Date: exact key or post-merge tolerance filter
    use_exact_date = "date" in match_fields and date_tol == 0
    use_tol_date   = "date" in match_fields and date_tol > 0
    if use_exact_date:
        gl_s["_date"]  = _normalise_date_str(gl_s["transaction_date"])
        sub_s["_date"] = _normalise_date_str(sub_s["transaction_date"])
        exact_join_cols.append("_date")
    elif use_tol_date:
        gl_s["_dord"]  = _date_ordinals(gl_s["transaction_date"])
        sub_s["_dord"] = _date_ordinals(sub_s["transaction_date"])

    if not exact_join_cols:
        logger.warning("Dynamic scenario %d has no exact join keys — skipped", scenario_id)
        return [], set(), set()

    merged = gl_s.merge(sub_s, on=exact_join_cols, suffixes=("_gl", "_sub"))
    if merged.empty:
        return [], set(), set()

    # Post-merge amount tolerance filter
    if use_tol_amount:
        amt_gl  = merged["amount_gl"]  if "amount_gl"  in merged.columns else merged["amount"]
        amt_sub = merged["amount_sub"] if "amount_sub" in merged.columns else merged["amount"]
        abs_diff = (amt_gl - amt_sub).abs()
        if amount_pct_tol > 0.0:
            pct_diff = abs_diff / amt_gl.abs().clip(lower=1e-9)
            merged = merged[(abs_diff <= amount_abs_tol) | (pct_diff <= amount_pct_tol)]
        else:
            merged = merged[abs_diff <= amount_abs_tol]

    # Post-merge date tolerance filter
    if use_tol_date:
        dord_gl  = merged["_dord_gl"]  if "_dord_gl"  in merged.columns else merged["_dord"]
        dord_sub = merged["_dord_sub"] if "_dord_sub" in merged.columns else merged["_dord"]
        merged = merged[(dord_gl - dord_sub).abs() <= date_tol]

    if merged.empty:
        return [], set(), set()

    gl_col  = "gl_id_gl"          if "gl_id_gl"          in merged.columns else "gl_id"
    sub_col = "subledger_id_sub"   if "subledger_id_sub"  in merged.columns else "subledger_id"

    return _greedy_1to1(
        merged, gl_col, sub_col, scenario_id, description, conf_score,
        match_fields=match_fields,
        date_tolerance_days=date_tol if date_tol else None,
        amount_tolerance_abs=amount_abs_tol if amount_abs_tol else None,
        amount_tolerance_pct=amount_pct_tol if amount_pct_tol else None,
    )


# ---------------------------------------------------------------------------
# Scenario implementations
# ---------------------------------------------------------------------------

def _scenario_1(
    gl_pool: pd.DataFrame, sub_pool: pd.DataFrame
) -> Tuple[List[MatchRecord], Set[str], Set[str]]:
    """
    Strict 1:1 — exact Vendor_Normalized, amount, transaction_date, entity.
    """
    if gl_pool.empty or sub_pool.empty:
        return [], set(), set()

    gl_s = gl_pool.copy()
    sub_s = sub_pool.copy()

    gl_s["_ak"]   = _normalise_amount(gl_s["amount"])
    sub_s["_ak"]  = _normalise_amount(sub_s["amount"])
    gl_s["_date"] = _normalise_date_str(gl_s["transaction_date"])
    sub_s["_date"] = _normalise_date_str(sub_s["transaction_date"])

    merged = gl_s.merge(
        sub_s,
        on=["Vendor_Normalized", "_ak", "_date", "entity"],
        suffixes=("_gl", "_sub"),
    )

    gl_col  = "gl_id_gl"  if "gl_id_gl"  in merged.columns else "gl_id"
    sub_col = "subledger_id_sub" if "subledger_id_sub" in merged.columns else "subledger_id"

    return _greedy_1to1(
        merged, gl_col, sub_col, 1,
        match_fields=["vendor", "amount", "date", "entity"],
        date_tolerance_days=0,
        amount_tolerance_abs=0,
        amount_tolerance_pct=0,
    )


def _scenario_2(
    gl_pool: pd.DataFrame, sub_pool: pd.DataFrame
) -> Tuple[List[MatchRecord], Set[str], Set[str]]:
    """
    Vendor + Amount + Entity match with narrow date tolerance ±30 days.

    Date ordinals are pre-computed on each pool (N+M operations) rather than
    on the merged cross-product (up to N×M operations).
    """
    if gl_pool.empty or sub_pool.empty:
        return [], set(), set()

    gl_s = gl_pool.copy()
    sub_s = sub_pool.copy()

    gl_s["_ak"]    = _normalise_amount(gl_s["amount"])
    sub_s["_ak"]   = _normalise_amount(sub_s["amount"])

    # Pre-compute date ordinals on individual pools (N+M rows, not N×M)
    gl_s["_dord"]  = _date_ordinals(gl_s["transaction_date"])
    sub_s["_dord"] = _date_ordinals(sub_s["transaction_date"])

    merged = gl_s.merge(
        sub_s,
        on=["Vendor_Normalized", "_ak", "entity"],
        suffixes=("_gl", "_sub"),
    )

    if merged.empty:
        return [], set(), set()

    merged = merged[
        (merged["_dord_gl"] - merged["_dord_sub"]).abs() <= DATE_TOLERANCE_NARROW
    ]

    gl_col  = "gl_id_gl"  if "gl_id_gl"  in merged.columns else "gl_id"
    sub_col = "subledger_id_sub" if "subledger_id_sub" in merged.columns else "subledger_id"

    return _greedy_1to1(
        merged, gl_col, sub_col, 2,
        match_fields=["vendor", "amount", "entity", "date"],
        date_tolerance_days=DATE_TOLERANCE_NARROW,
        amount_tolerance_abs=0,
        amount_tolerance_pct=0,
    )


def _scenario_3(
    gl_pool: pd.DataFrame, sub_pool: pd.DataFrame
) -> Tuple[List[MatchRecord], Set[str], Set[str]]:
    """
    Vendor + Amount + Entity match with wide date tolerance ±60 days.

    Identical join criteria to Scenario 2 but accepts a wider date window,
    catching late-posted or accrual-reversed transactions. Records that
    already matched within ±30 days are excluded (consumed by Scenario 2).
    """
    if gl_pool.empty or sub_pool.empty:
        return [], set(), set()

    gl_s = gl_pool.copy()
    sub_s = sub_pool.copy()

    gl_s["_ak"]    = _normalise_amount(gl_s["amount"])
    sub_s["_ak"]   = _normalise_amount(sub_s["amount"])

    # Pre-compute date ordinals on individual pools
    gl_s["_dord"]  = _date_ordinals(gl_s["transaction_date"])
    sub_s["_dord"] = _date_ordinals(sub_s["transaction_date"])

    merged = gl_s.merge(
        sub_s,
        on=["Vendor_Normalized", "_ak", "entity"],
        suffixes=("_gl", "_sub"),
    )

    if merged.empty:
        return [], set(), set()

    date_gap = (merged["_dord_gl"] - merged["_dord_sub"]).abs()
    merged = merged[date_gap <= DATE_TOLERANCE_WIDE]

    gl_col  = "gl_id_gl"  if "gl_id_gl"  in merged.columns else "gl_id"
    sub_col = "subledger_id_sub" if "subledger_id_sub" in merged.columns else "subledger_id"

    return _greedy_1to1(
        merged, gl_col, sub_col, 3,
        match_fields=["vendor", "amount", "entity", "date"],
        date_tolerance_days=DATE_TOLERANCE_WIDE,
        amount_tolerance_abs=0,
        amount_tolerance_pct=0,
    )


# ---------------------------------------------------------------------------
# Main pipeline entry point
# ---------------------------------------------------------------------------

def _resolve_det_cols(column_map: Optional[Dict] = None) -> Dict[str, Any]:
    """
    Resolve actual column names from column_map, falling back to hardcoded defaults.
    Returns a dict with keys: a_id, b_id, amount, date, entity (entity may be None).
    Note: vendor is always "Vendor_Normalized" — the derived column added by normalization.
    """
    if not column_map:
        return {
            "a_id":   "gl_id",
            "b_id":   "subledger_id",
            "amount": "amount",
            "date":   "transaction_date",
            "entity": "entity",
        }
    a = column_map.get("side_a", {})
    b = column_map.get("side_b", {})
    return {
        "a_id":   a.get("id") or "gl_id",
        "b_id":   b.get("id") or "subledger_id",
        "amount": a.get("amount") or "amount",
        "date":   a.get("date") or "transaction_date",
        "entity": a.get("entity"),          # None if entity column not mapped
    }


def _standardize_df(
    df: pd.DataFrame,
    cols: Dict[str, Any],
    side: str,  # "a" (GL) or "b" (Sub)
) -> pd.DataFrame:
    """
    Rename user-defined column names to the standard names expected by scenario functions.
    Only renames columns that differ from the standard names.  Returns a copy.
    """
    id_col  = cols["a_id"]  if side == "a" else cols["b_id"]
    std_id  = "gl_id"       if side == "a" else "subledger_id"
    std_amt = "amount"
    std_dt  = "transaction_date"
    std_ent = "entity"

    rename = {}
    if cols["amount"] != std_amt and cols["amount"] in df.columns:
        rename[cols["amount"]] = std_amt
    if cols["date"] != std_dt and cols["date"] in df.columns:
        rename[cols["date"]] = std_dt
    if cols["entity"] and cols["entity"] != std_ent and cols["entity"] in df.columns:
        rename[cols["entity"]] = std_ent
    if id_col != std_id and id_col in df.columns:
        rename[id_col] = std_id

    return df.rename(columns=rename) if rename else df.copy()


def run_deterministic_matching(
    gl_df: pd.DataFrame,
    sub_df: pd.DataFrame,
    column_map: Optional[Dict] = None,
    scenario_configs: Optional[List[Dict]] = None,
) -> DeterministicResult:
    """
    Run the deterministic matching pipeline.

    Args:
        gl_df:            GL DataFrame (clean_data after vendor normalization).
        sub_df:           Subledger DataFrame.
        column_map:       Optional column role mapping from runtime config. When provided,
                          column names are resolved dynamically. Falls back to hardcoded
                          defaults when None or empty (legacy path — preserves all existing tests).
        scenario_configs: Optional list of scenario config dicts from matching_config.
                          When non-empty, overrides the 3 hardcoded scenarios.
                          When None/empty, runs the 3 hardcoded scenarios.

    Returns:
        DeterministicResult — matches, residual DataFrames, and counts.

    Raises:
        ValueError — if a required column is absent from either DataFrame.
    """
    cols = _resolve_det_cols(column_map)

    # Standardize column names to what the scenario functions expect
    gl_std  = _standardize_df(gl_df,  cols, "a")
    sub_std = _standardize_df(sub_df, cols, "b")

    # Entity column: if not mapped, drop from standard DataFrames to skip entity blocking
    has_entity = (cols["entity"] is not None) or ("entity" in gl_df.columns)
    if not has_entity and "entity" in gl_std.columns:
        # entity col exists with default name; keep it since column_map is default
        pass
    elif cols["entity"] is None and "entity" not in gl_std.columns:
        # No entity column — add a dummy constant entity so existing merge logic works
        gl_std  = gl_std.copy();  gl_std["entity"]  = "__no_entity__"
        sub_std = sub_std.copy(); sub_std["entity"] = "__no_entity__"

    _required_gl  = {"gl_id", "Vendor_Normalized", "amount", "transaction_date", "entity"}
    _required_sub = {"subledger_id", "Vendor_Normalized", "amount", "transaction_date", "entity"}

    # Only validate columns when the DataFrame has rows; empty pools are valid inputs
    # (the residual pool may be exhausted by earlier phases).
    if len(gl_std) > 0:
        missing_gl = _required_gl - set(gl_std.columns)
        if missing_gl:
            raise ValueError(f"GL DataFrame missing required columns: {missing_gl}")
    if len(sub_std) > 0:
        missing_sub = _required_sub - set(sub_std.columns)
        if missing_sub:
            raise ValueError(f"Subledger DataFrame missing required columns: {missing_sub}")

    all_used_gl:  Set[str] = set()
    all_used_sub: Set[str] = set()
    all_matches:  List[MatchRecord] = []
    scenario_counts: Dict[int, int] = {}

    logger.info(
        "Deterministic matching started: GL=%d rows, Sub=%d rows",
        len(gl_std), len(sub_std),
    )
    t_total = time.perf_counter()

    if scenario_configs:
        # Dynamic path — use user-configured scenarios from matching_config
        logger.info("Using %d dynamic scenario(s) from matching_config", len(scenario_configs))
        for i, sc in enumerate(scenario_configs, start=1):
            scenario_num = int(sc.get("scenario_id", i))
            gl_remaining  = _filter_pool(gl_std,  "gl_id",        all_used_gl)
            sub_remaining = _filter_pool(sub_std, "subledger_id", all_used_sub)
            logger.info(
                "Dynamic scenario %d starting: GL pool=%d, Sub pool=%d",
                scenario_num, len(gl_remaining), len(sub_remaining),
            )
            t0 = time.perf_counter()
            new_matches, new_gl, new_sub = _run_dynamic_scenario(
                gl_remaining, sub_remaining, sc, scenario_num
            )
            elapsed = time.perf_counter() - t0
            logger.info(
                "Dynamic scenario %d complete: matches=%d, elapsed=%.3fs",
                scenario_num, len(new_matches), elapsed,
            )
            all_matches.extend(new_matches)
            all_used_gl.update(new_gl)
            all_used_sub.update(new_sub)
            scenario_counts[scenario_num] = len(new_matches)
    else:
        # Legacy path — 3 hardcoded scenarios (preserves all existing tests)
        scenario_counts = {1: 0, 2: 0, 3: 0}
        for scenario_fn, scenario_num in [
            (_scenario_1, 1),
            (_scenario_2, 2),
            (_scenario_3, 3),
        ]:
            gl_remaining  = _filter_pool(gl_std,  "gl_id",        all_used_gl)
            sub_remaining = _filter_pool(sub_std, "subledger_id", all_used_sub)

            logger.info(
                "Scenario %d starting: GL pool=%d, Sub pool=%d",
                scenario_num, len(gl_remaining), len(sub_remaining),
            )
            t0 = time.perf_counter()
            new_matches, new_gl, new_sub = scenario_fn(gl_remaining, sub_remaining)
            elapsed = time.perf_counter() - t0
            logger.info(
                "Scenario %d complete: matches=%d, elapsed=%.3fs",
                scenario_num, len(new_matches), elapsed,
            )
            all_matches.extend(new_matches)
            all_used_gl.update(new_gl)
            all_used_sub.update(new_sub)
            scenario_counts[scenario_num] = len(new_matches)

    # Build residual DataFrames (unmatched records) — return in standardized column names
    residual_gl  = _filter_pool(gl_std,  "gl_id",        all_used_gl).copy()
    residual_sub = _filter_pool(sub_std, "subledger_id", all_used_sub).copy()

    logger.info(
        "Deterministic matching complete: total_matches=%d, "
        "residual_gl=%d, residual_sub=%d, total_elapsed=%.3fs",
        len(all_matches),
        len(residual_gl), len(residual_sub),
        time.perf_counter() - t_total,
    )

    return DeterministicResult(
        matches=        all_matches,
        residual_gl=    residual_gl,
        residual_sub=   residual_sub,
        total_gl=       len(gl_std),
        total_sub=      len(sub_std),
        scenario_counts=scenario_counts,
    )
