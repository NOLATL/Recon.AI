"""
Deterministic Matching Service — Phase 4: preprocessed → deterministic_complete

Four ordered scenarios (each scenario operates only on records not consumed by prior ones):

  Scenario 1 — Strict 1:1
    Exact match on: Vendor_Normalized, amount (rounded to 2 dp), transaction_date, entity
    Confidence: 1.00 | grouping_type: "one_to_one"

  Scenario 2 — Vendor + Amount + Date tolerance
    Exact match on: Vendor_Normalized, amount (rounded to 2 dp)
    Date tolerance: abs(date_gl − date_sub) ≤ 60 days
    Confidence: 0.95 | grouping_type: "one_to_one"

  Scenario 3 — Amount + Entity + Date tolerance
    Exact match on: amount (rounded to 2 dp), entity
    Date tolerance: abs(date_gl − date_sub) ≤ 60 days
    Confidence: 0.85 | grouping_type: "one_to_one"

  Scenario 4 — Deterministic grouping (exact sum equality, pairs only)
    N:1 — pairs of GL rows (same entity) summing to one Sub amount
    1:N — one GL row whose amount equals the sum of a pair of Sub rows (same entity)
    Confidence: 0.75 | grouping_type: "many_to_one" | "one_to_many"
    Guard: skipped when either residual pool exceeds SCENARIO_4_POOL_LIMIT (50) records

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
from dataclasses import dataclass, field
from itertools import combinations
from typing import Dict, List, Set, Tuple

import pandas as pd

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DATE_TOLERANCE_DAYS: int = 60
MAX_GROUP_SIZE: int = 2          # pairs only — keeps combinatorial cost O(n²) per entity
SCENARIO_4_POOL_LIMIT: int = 50  # skip Scenario 4 when either pool exceeds this size

_EPOCH = pd.Timestamp("1970-01-01")

_SCENARIO_META: Dict[int, dict] = {
    1: {
        "description": "Strict 1:1: exact Vendor_Normalized, amount, date, entity",
        "confidence_score": 1.00,
    },
    2: {
        "description": "Vendor + Amount match with date tolerance ±60 days",
        "confidence_score": 0.95,
    },
    3: {
        "description": "Amount + Entity match with date tolerance ±60 days",
        "confidence_score": 0.85,
    },
    4: {
        "description": "Deterministic grouping: exact sum equality, bounded search",
        "confidence_score": 0.75,
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
    user_status: str = "auto_confirmed"
    override_flag: bool = False

    def to_dict(self) -> dict:
        return {
            "match_id":             self.match_id,
            "record_ids_A":         self.record_ids_A,
            "record_ids_B":         self.record_ids_B,
            "scenario_id":          self.scenario_id,
            "scenario_description": self.scenario_description,
            "confidence_score":     self.confidence_score,
            "grouping_type":        self.grouping_type,
            "user_status":          self.user_status,
            "override_flag":        self.override_flag,
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
) -> Tuple[List[MatchRecord], Set[str], Set[str]]:
    """
    Walk merged rows in order, producing 1:1 matches; each ID used at most once.
    Returns (matches, used_gl_ids, used_sub_ids).
    """
    matches: List[MatchRecord] = []
    used_gl: Set[str] = set()
    used_sub: Set[str] = set()

    for _, row in merged.iterrows():
        gl_id  = str(row[gl_id_col])
        sub_id = str(row[sub_id_col])
        if gl_id not in used_gl and sub_id not in used_sub:
            used_gl.add(gl_id)
            used_sub.add(sub_id)
            matches.append(_make_match_1to1(row, gl_id_col, sub_id_col, scenario_id))

    return matches, used_gl, used_sub


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

    return _greedy_1to1(merged, gl_col, sub_col, 1)


def _scenario_2(
    gl_pool: pd.DataFrame, sub_pool: pd.DataFrame
) -> Tuple[List[MatchRecord], Set[str], Set[str]]:
    """
    Vendor + Amount match with date tolerance ±60 days (no entity constraint).

    Date ordinals are pre-computed on each pool (N+M operations) rather than
    on the merged cross-product (up to N×M operations).
    """
    if gl_pool.empty or sub_pool.empty:
        return [], set(), set()

    gl_s = gl_pool.copy()
    sub_s = sub_pool.copy()

    gl_s["_ak"]       = _normalise_amount(gl_s["amount"])
    sub_s["_ak"]      = _normalise_amount(sub_s["amount"])

    # Pre-compute date ordinals on individual pools (N+M rows, not N×M)
    gl_s["_dord"]  = _date_ordinals(gl_s["transaction_date"])
    sub_s["_dord"] = _date_ordinals(sub_s["transaction_date"])

    merged = gl_s.merge(
        sub_s,
        on=["Vendor_Normalized", "_ak"],
        suffixes=("_gl", "_sub"),
    )

    if merged.empty:
        return [], set(), set()

    # Date filter using pre-computed integer ordinals — pure vectorised subtraction
    merged = merged[
        (merged["_dord_gl"] - merged["_dord_sub"]).abs() <= DATE_TOLERANCE_DAYS
    ]

    gl_col  = "gl_id_gl"  if "gl_id_gl"  in merged.columns else "gl_id"
    sub_col = "subledger_id_sub" if "subledger_id_sub" in merged.columns else "subledger_id"

    return _greedy_1to1(merged, gl_col, sub_col, 2)


def _scenario_3(
    gl_pool: pd.DataFrame, sub_pool: pd.DataFrame
) -> Tuple[List[MatchRecord], Set[str], Set[str]]:
    """
    Amount + Entity match with date tolerance ±60 days (no vendor constraint).

    Date ordinals are pre-computed on each pool (N+M operations).
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
        on=["_ak", "entity"],
        suffixes=("_gl", "_sub"),
    )

    if merged.empty:
        return [], set(), set()

    merged = merged[
        (merged["_dord_gl"] - merged["_dord_sub"]).abs() <= DATE_TOLERANCE_DAYS
    ]

    gl_col  = "gl_id_gl"  if "gl_id_gl"  in merged.columns else "gl_id"
    sub_col = "subledger_id_sub" if "subledger_id_sub" in merged.columns else "subledger_id"

    return _greedy_1to1(merged, gl_col, sub_col, 3)


def _scenario_4(
    gl_pool: pd.DataFrame, sub_pool: pd.DataFrame
) -> Tuple[List[MatchRecord], Set[str], Set[str]]:
    """
    Deterministic grouping — exact sum equality, bounded by MAX_GROUP_SIZE (pairs only).

    Only runs when both pools are ≤ SCENARIO_4_POOL_LIMIT records (enforced by the
    caller in run_deterministic_matching()).

    N:1: combinations of 2–MAX_GROUP_SIZE GL rows (same entity) that sum to one Sub amount.
    1:N: one GL row whose amount equals the sum of 2–MAX_GROUP_SIZE Sub rows (same entity).

    Key efficiency improvements over the naïve approach:
      1. Amount pre-filter: only candidates with amount ≤ target can contribute to a sum.
         This reduces C(n, k) to C(m, k) where m << n for typical distributions.
      2. Infeasibility guard: if sum(all_candidates) < target, skip immediately.
      3. Mutable availability sets: O(1) discard/difference_update instead of
         rebuilding a filter list from scratch on every outer-loop iteration.
      4. Vectorised dict construction: dict(zip(...)) instead of iterrows().
    """
    if gl_pool.empty or sub_pool.empty:
        return [], set(), set()

    matches: List[MatchRecord] = []
    used_gl: Set[str] = set()
    used_sub: Set[str] = set()

    entities = sorted(
        set(gl_pool["entity"].dropna().unique()) &
        set(sub_pool["entity"].dropna().unique())
    )

    for entity in entities:
        gl_e  = gl_pool[gl_pool["entity"] == entity].copy()
        sub_e = sub_pool[sub_pool["entity"] == entity].copy()

        gl_e["_ak"]  = _normalise_amount(gl_e["amount"])
        sub_e["_ak"] = _normalise_amount(sub_e["amount"])

        # Vectorised dict construction — 10–100× faster than iterrows for large pools
        gl_amount_map  = dict(zip(gl_e["gl_id"].astype(str),        gl_e["_ak"]))
        sub_amount_map = dict(zip(sub_e["subledger_id"].astype(str), sub_e["_ak"]))

        # Mutable availability sets — start with globally-consumed IDs already excluded
        avail_gl  = set(gl_amount_map.keys()) - used_gl
        avail_sub = set(sub_amount_map.keys()) - used_sub

        # ── N:1: multiple GL rows → one Sub row ──────────────────────────────
        for sub_id in list(avail_sub):          # snapshot; avail_sub mutates below
            if sub_id not in avail_sub:         # may have been consumed in this loop
                continue

            sub_amount = sub_amount_map[sub_id]

            # Pre-filter: only GL records with amount ≤ sub_amount can contribute.
            # Sort descending so larger-value combinations are tried first (shorter
            # paths to the target sum → combinatorial tree pruned earlier).
            candidates = sorted(
                (g for g in avail_gl if gl_amount_map[g] <= sub_amount),
                key=lambda g: -gl_amount_map[g],
            )

            # Infeasibility guard: if all candidates together can't reach the target,
            # no combination can — skip without touching the combinations iterator.
            if not candidates:
                continue
            if round(sum(gl_amount_map[g] for g in candidates), 2) < sub_amount:
                continue

            found = False
            for size in range(2, min(MAX_GROUP_SIZE + 1, len(candidates) + 1)):
                if found:
                    break
                for combo in combinations(candidates, size):
                    if round(sum(gl_amount_map[g] for g in combo), 2) == sub_amount:
                        avail_sub.discard(sub_id)
                        avail_gl.difference_update(combo)
                        used_sub.add(sub_id)
                        used_gl.update(combo)
                        matches.append(MatchRecord(
                            match_id=str(uuid.uuid4()),
                            record_ids_A=list(combo),
                            record_ids_B=[sub_id],
                            scenario_id=4,
                            scenario_description=_SCENARIO_META[4]["description"],
                            confidence_score=_SCENARIO_META[4]["confidence_score"],
                            grouping_type="many_to_one",
                        ))
                        found = True
                        break

        # ── 1:N: one GL row → multiple Sub rows ──────────────────────────────
        for gl_id in list(avail_gl):            # snapshot; avail_gl mutates below
            if gl_id not in avail_gl:
                continue

            gl_amount = gl_amount_map[gl_id]

            candidates = sorted(
                (s for s in avail_sub if sub_amount_map[s] <= gl_amount),
                key=lambda s: -sub_amount_map[s],
            )

            if not candidates:
                continue
            if round(sum(sub_amount_map[s] for s in candidates), 2) < gl_amount:
                continue

            found = False
            for size in range(2, min(MAX_GROUP_SIZE + 1, len(candidates) + 1)):
                if found:
                    break
                for combo in combinations(candidates, size):
                    if round(sum(sub_amount_map[s] for s in combo), 2) == gl_amount:
                        avail_gl.discard(gl_id)
                        avail_sub.difference_update(combo)
                        used_gl.add(gl_id)
                        used_sub.update(combo)
                        matches.append(MatchRecord(
                            match_id=str(uuid.uuid4()),
                            record_ids_A=[gl_id],
                            record_ids_B=list(combo),
                            scenario_id=4,
                            scenario_description=_SCENARIO_META[4]["description"],
                            confidence_score=_SCENARIO_META[4]["confidence_score"],
                            grouping_type="one_to_many",
                        ))
                        found = True
                        break

    return matches, used_gl, used_sub


# ---------------------------------------------------------------------------
# Main pipeline entry point
# ---------------------------------------------------------------------------

def run_deterministic_matching(
    gl_df: pd.DataFrame,
    sub_df: pd.DataFrame,
) -> DeterministicResult:
    """
    Run the 4-tier deterministic matching pipeline.

    Args:
        gl_df:  GL DataFrame — must contain columns:
                  gl_id, Vendor_Normalized, amount, transaction_date, entity
        sub_df: Subledger DataFrame — must contain columns:
                  subledger_id, Vendor_Normalized, amount, transaction_date, entity

    Returns:
        DeterministicResult — matches, residual DataFrames, and counts.

    Raises:
        ValueError — if a required column is absent from either DataFrame.
    """
    _required_gl  = {"gl_id", "Vendor_Normalized", "amount", "transaction_date", "entity"}
    _required_sub = {"subledger_id", "Vendor_Normalized", "amount", "transaction_date", "entity"}

    # Only validate columns when the DataFrame has rows; empty pools are valid inputs
    # (the residual pool may be exhausted by earlier phases).
    if len(gl_df) > 0:
        missing_gl = _required_gl - set(gl_df.columns)
        if missing_gl:
            raise ValueError(f"GL DataFrame missing required columns: {missing_gl}")
    if len(sub_df) > 0:
        missing_sub = _required_sub - set(sub_df.columns)
        if missing_sub:
            raise ValueError(f"Subledger DataFrame missing required columns: {missing_sub}")

    all_used_gl:  Set[str] = set()
    all_used_sub: Set[str] = set()
    all_matches:  List[MatchRecord] = []
    scenario_counts: Dict[int, int] = {1: 0, 2: 0, 3: 0, 4: 0}

    logger.info(
        "Deterministic matching started: GL=%d rows, Sub=%d rows",
        len(gl_df), len(sub_df),
    )
    t_total = time.perf_counter()

    for scenario_fn, scenario_num in [
        (_scenario_1, 1),
        (_scenario_2, 2),
        (_scenario_3, 3),
        (_scenario_4, 4),
    ]:
        gl_remaining  = _filter_pool(gl_df,  "gl_id",        all_used_gl)
        sub_remaining = _filter_pool(sub_df, "subledger_id", all_used_sub)

        # Scenario 4 is combinatorial — skip when the residual pool is too large.
        if scenario_num == 4 and (
            len(gl_remaining) > SCENARIO_4_POOL_LIMIT
            or len(sub_remaining) > SCENARIO_4_POOL_LIMIT
        ):
            logger.info(
                "Scenario 4 skipped: GL pool=%d, Sub pool=%d exceed limit=%d",
                len(gl_remaining), len(sub_remaining), SCENARIO_4_POOL_LIMIT,
            )
            scenario_counts[4] = 0
            continue

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

    # Build residual DataFrames (unmatched records)
    residual_gl  = _filter_pool(gl_df,  "gl_id",        all_used_gl).copy()
    residual_sub = _filter_pool(sub_df, "subledger_id", all_used_sub).copy()

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
        total_gl=       len(gl_df),
        total_sub=      len(sub_df),
        scenario_counts=scenario_counts,
    )
