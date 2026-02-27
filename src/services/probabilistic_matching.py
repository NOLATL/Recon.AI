"""
Probabilistic Matching Service — Phase 5: deterministic_review_complete → probabilistic_complete

Operates exclusively on the residual pool left by the deterministic layer.
Never mutates deterministic matches.

Similarity formula (from ARCHITECTURE_CONSTRAINTS.md):
  final_similarity = 0.40 * vendor_similarity
                   + 0.35 * amount_similarity
                   + 0.15 * date_similarity
                   + 0.10 * entity_similarity

Blocking rules (minimum criteria before scoring):
  1. Same entity
  2. Date difference ≤ DATE_TOLERANCE_DAYS (60)
  3. Amount difference ≤ max(AMOUNT_PCT_TOLERANCE * max(|a|, |b|), AMOUNT_ABS_TOLERANCE)

Matching algorithm:
  Step 1 — 1:1 matching
    All candidate pairs that pass blocking and score ≥ threshold.
    Sort by final_similarity descending; greedy assignment (highest first).

  Step 2 — N:1 grouping
    For each entity group in remaining records, search combinations of
    2–MAX_GROUP_SIZE GL rows whose total amount falls in the Sub's tolerance band.
    Group-level similarity computed as:
      vendor_sim  = mean of individual GL→Sub vendor similarities
      amount_sim  = _amount_sim(sum(GL amounts), Sub amount)
      date_sim    = mean of individual GL→Sub date similarities
      entity_sim  = 1.0 (guaranteed by entity grouping)
    Only accepted if final group similarity ≥ threshold.

  Step 3 — 1:N grouping
    Mirror of N:1: one GL row, combinations of 2–MAX_GROUP_SIZE Sub rows.

Threshold:
  Provided via `threshold` parameter; stored in runtime["config"]["threshold"].
  Default: DEFAULT_THRESHOLD (0.80).

User status:
  All probabilistic matches start as "pending" (require human review).
  This differs from deterministic matches ("auto_confirmed").
"""

import logging
import time
import uuid
from dataclasses import dataclass, field
from itertools import combinations
from typing import Dict, List, Optional, Set, Tuple

import pandas as pd
from rapidfuzz import fuzz


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DATE_TOLERANCE_DAYS:  int   = 60
MAX_GROUP_SIZE:       int   = 5
AMOUNT_PCT_TOLERANCE: float = 0.20     # 20 % of the larger absolute amount
AMOUNT_ABS_TOLERANCE: float = 5.00    # always allow at least $5 difference
DEFAULT_THRESHOLD:    float = 0.80

DEFAULT_WEIGHTS: Dict[str, float] = {
    "vendor": 0.40,
    "amount": 0.35,
    "date":   0.15,
    "entity": 0.10,
}

_EPOCH  = pd.Timestamp("1970-01-01")
logger  = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Result dataclasses
# ---------------------------------------------------------------------------

@dataclass
class ProbabilisticMatchRecord:
    """One probabilistic match (pending human review)."""
    match_id:          str
    record_ids_A:      List[str]    # GL gl_id values
    record_ids_B:      List[str]    # Subledger subledger_id values
    final_similarity:  float
    component_scores:  Dict[str, float]   # vendor/amount/date/entity_similarity
    grouping_type:     str          # "one_to_one" | "many_to_one" | "one_to_many"
    user_status:       str  = "pending"
    override_flag:     bool = False

    def to_dict(self) -> dict:
        return {
            "match_id":         self.match_id,
            "record_ids_A":     self.record_ids_A,
            "record_ids_B":     self.record_ids_B,
            "final_similarity": self.final_similarity,
            "component_scores": self.component_scores,
            "grouping_type":    self.grouping_type,
            "user_status":      self.user_status,
            "override_flag":    self.override_flag,
        }


@dataclass
class ProbabilisticResult:
    """Full output of run_probabilistic_matching()."""
    matches:        List[ProbabilisticMatchRecord]
    residual_gl:    pd.DataFrame
    residual_sub:   pd.DataFrame
    total_gl:       int
    total_sub:      int
    threshold_used: float
    weights_used:   Dict[str, float]

    @property
    def matched_gl(self) -> int:
        return self.total_gl - len(self.residual_gl)

    @property
    def matched_sub(self) -> int:
        return self.total_sub - len(self.residual_sub)

    def to_match_list(self) -> List[dict]:
        return [m.to_dict() for m in self.matches]


# ---------------------------------------------------------------------------
# Similarity helpers
# ---------------------------------------------------------------------------

def _vendor_sim(norm_a: str, norm_b: str) -> float:
    """Token-sort ratio (0.0–1.0). Case-insensitive via pre-normalised strings."""
    return fuzz.token_sort_ratio(str(norm_a), str(norm_b)) / 100.0


def _amount_sim(amount_a: float, amount_b: float) -> float:
    """1.0 for identical amounts; decreases linearly toward 0 as difference grows."""
    base = max(abs(amount_a), abs(amount_b), 0.01)
    return max(0.0, 1.0 - abs(amount_a - amount_b) / base)


def _date_sim(date_a, date_b) -> float:
    """1.0 for same date; 0.0 at DATE_TOLERANCE_DAYS; clamped below 0."""
    diff = abs((pd.to_datetime(date_a) - pd.to_datetime(date_b)).days)
    return max(0.0, 1.0 - diff / DATE_TOLERANCE_DAYS)


def _date_sim_ordinals(dord_a: Optional[int], dord_b: Optional[int]) -> float:
    """Date similarity from pre-computed integer day ordinals. Avoids pd.to_datetime per-pair."""
    if dord_a is None or dord_b is None:
        return 0.0
    diff = abs(dord_a - dord_b)
    return max(0.0, 1.0 - diff / DATE_TOLERANCE_DAYS)


def _entity_sim(entity_a: str, entity_b: str) -> float:
    """Binary: 1.0 if same entity, 0.0 otherwise."""
    return 1.0 if str(entity_a) == str(entity_b) else 0.0


def _final_sim(comp: Dict[str, float], weights: Dict[str, float]) -> float:
    """Weighted sum of component similarities."""
    return (
        weights["vendor"] * comp["vendor_similarity"] +
        weights["amount"] * comp["amount_similarity"] +
        weights["date"]   * comp["date_similarity"]   +
        weights["entity"] * comp["entity_similarity"]
    )


# ---------------------------------------------------------------------------
# Blocking
# ---------------------------------------------------------------------------

def _passes_block(
    amount_gl: float,
    date_gl,
    entity_gl: str,
    amount_sub: float,
    date_sub,
    entity_sub: str,
) -> bool:
    """Return True if the pair is eligible for similarity scoring."""
    if str(entity_gl) != str(entity_sub):
        return False
    if abs((pd.to_datetime(date_gl) - pd.to_datetime(date_sub)).days) > DATE_TOLERANCE_DAYS:
        return False
    base = max(abs(amount_gl), abs(amount_sub), 0.01)
    if abs(amount_gl - amount_sub) > max(AMOUNT_PCT_TOLERANCE * base, AMOUNT_ABS_TOLERANCE):
        return False
    return True


# ---------------------------------------------------------------------------
# Step 1 — 1:1 matching
# ---------------------------------------------------------------------------

def _match_1to1(
    gl_pool: pd.DataFrame,
    sub_pool: pd.DataFrame,
    threshold: float,
    weights: Dict[str, float],
) -> Tuple[List[ProbabilisticMatchRecord], Set[str], Set[str], int]:
    """
    Greedy 1:1 matching sorted by final_similarity descending.
    Records are consumed at most once.

    Optimisations vs. naive nested iterrows:
      - Entity-keyed merge creates the cross-product only within each entity group
        (blocks cross-entity pairs without a Python loop).
      - Vectorised date and amount filters reduce candidate pairs before any
        Python-level scoring.
      - Date ordinals pre-computed on each pool (N+M rows) instead of inside the
        merged frame (N×M rows).
      - _date_sim_ordinals replaces per-pair pd.to_datetime calls.

    Returns:
        (matches, used_gl_ids, used_sub_ids, comparisons_after_blocking)
    """
    if gl_pool.empty or sub_pool.empty:
        return [], set(), set(), 0

    # Working copies — pre-compute date ordinals and float amounts on each pool
    # (N + M rows) before the merge (N × M rows).
    gl_w = gl_pool[["gl_id", "Vendor_Normalized", "amount", "transaction_date", "entity"]].copy()
    sub_w = sub_pool[["subledger_id", "Vendor_Normalized", "amount", "transaction_date", "entity"]].copy()

    gl_w["gl_dord"]  = (pd.to_datetime(gl_w["transaction_date"],  errors="coerce") - _EPOCH).dt.days
    sub_w["sub_dord"] = (pd.to_datetime(sub_w["transaction_date"], errors="coerce") - _EPOCH).dt.days
    gl_w["gl_amt"]   = gl_w["amount"].astype(float)
    sub_w["sub_amt"] = sub_w["amount"].astype(float)

    # Cross-join within entity only (entity is the blocking key).
    # Columns unique to gl_w (gl_id, gl_dord, gl_amt) keep their names;
    # shared columns (Vendor_Normalized, amount, transaction_date) get _gl/_sub suffixes.
    merged = gl_w.merge(sub_w, on="entity", suffixes=("_gl", "_sub"))

    # Vectorised date filter — NaT arithmetic yields NaN → NaN ≤ 60 is False → filtered out.
    merged = merged[(merged["gl_dord"] - merged["sub_dord"]).abs() <= DATE_TOLERANCE_DAYS]

    # Vectorised amount filter.
    if not merged.empty:
        base = merged[["gl_amt", "sub_amt"]].abs().max(axis=1).clip(lower=0.01)
        tol  = (AMOUNT_PCT_TOLERANCE * base).clip(lower=AMOUNT_ABS_TOLERANCE)
        merged = merged[(merged["gl_amt"] - merged["sub_amt"]).abs() <= tol]

    comparisons_after_blocking = len(merged)

    if merged.empty:
        return [], set(), set(), comparisons_after_blocking

    # Score surviving candidates — vendor sim still requires a Python loop.
    candidates: List[Tuple[float, Dict[str, float], str, str]] = []
    for row in merged.itertuples(index=False):
        comp = {
            "vendor_similarity": _vendor_sim(row.Vendor_Normalized_gl, row.Vendor_Normalized_sub),
            "amount_similarity": _amount_sim(row.gl_amt, row.sub_amt),
            "date_similarity":   _date_sim_ordinals(
                None if pd.isna(row.gl_dord)  else int(row.gl_dord),
                None if pd.isna(row.sub_dord) else int(row.sub_dord),
            ),
            "entity_similarity": 1.0,  # guaranteed by entity merge
        }
        sim = _final_sim(comp, weights)
        if sim >= threshold:
            candidates.append((sim, comp, str(row.gl_id), str(row.subledger_id)))

    candidates.sort(key=lambda x: x[0], reverse=True)

    matches: List[ProbabilisticMatchRecord] = []
    used_gl:  Set[str] = set()
    used_sub: Set[str] = set()

    for sim, comp, gl_id, sub_id in candidates:
        if gl_id not in used_gl and sub_id not in used_sub:
            used_gl.add(gl_id)
            used_sub.add(sub_id)
            matches.append(ProbabilisticMatchRecord(
                match_id=         str(uuid.uuid4()),
                record_ids_A=     [gl_id],
                record_ids_B=     [sub_id],
                final_similarity= round(sim, 4),
                component_scores= {k: round(v, 4) for k, v in comp.items()},
                grouping_type=    "one_to_one",
            ))

    return matches, used_gl, used_sub, comparisons_after_blocking


# ---------------------------------------------------------------------------
# Step 2 — N:1 grouping
# ---------------------------------------------------------------------------

def _match_n_to_1(
    gl_pool: pd.DataFrame,
    sub_pool: pd.DataFrame,
    threshold: float,
    weights: Dict[str, float],
) -> Tuple[List[ProbabilisticMatchRecord], Set[str], Set[str], int, int]:
    """
    For each entity group: search combinations of 2–MAX_GROUP_SIZE GL rows
    whose total amount is within the tolerance band of a single Sub amount.
    Accepts if group-level final_similarity ≥ threshold.

    Optimisations vs. naive iterrows version:
      - Vectorised column extraction per entity group (avoids iterrows).
      - Date ordinals pre-computed per entity pool instead of inside the combo loop.
      - Index-based availability sets with O(1) discard (no O(n) list rebuild per sub row).
      - Date pre-filter reduces GL candidates before combinations() is called.
      - Infeasibility guard: if the sum of all date-filtered candidates cannot reach
        sub_amount (within tolerance), the sub row is skipped entirely.
      - Candidates sorted descending by amount: largest-value combinations found
        sooner, which terminates the search for a given sub row earlier.

    Returns:
        (matches, used_gl_ids, used_sub_ids, combos_evaluated, max_depth_reached)
    """
    if gl_pool.empty or sub_pool.empty:
        return [], set(), set(), 0, 0

    matches:  List[ProbabilisticMatchRecord] = []
    used_gl:  Set[str] = set()
    used_sub: Set[str] = set()
    combos_evaluated  = 0
    max_depth_reached = 0

    entities = sorted(
        set(gl_pool["entity"].dropna().unique()) &
        set(sub_pool["entity"].dropna().unique())
    )

    for entity in entities:
        gl_e  = gl_pool[gl_pool["entity"] == entity]
        sub_e = sub_pool[sub_pool["entity"] == entity]

        if gl_e.empty or sub_e.empty:
            continue

        # Vectorised extraction — avoids iterrows per combo iteration.
        gl_ids  = gl_e["gl_id"].astype(str).tolist()
        gl_amts = gl_e["amount"].astype(float).tolist()
        gl_vns  = gl_e["Vendor_Normalized"].astype(str).tolist()
        _gl_dord_raw = (pd.to_datetime(gl_e["transaction_date"], errors="coerce") - _EPOCH).dt.days
        gl_dords = [None if pd.isna(v) else int(v) for v in _gl_dord_raw]

        sub_ids   = sub_e["subledger_id"].astype(str).tolist()
        sub_amts  = sub_e["amount"].astype(float).tolist()
        sub_vns   = sub_e["Vendor_Normalized"].astype(str).tolist()
        _sub_dord_raw = (pd.to_datetime(sub_e["transaction_date"], errors="coerce") - _EPOCH).dt.days
        sub_dords = [None if pd.isna(v) else int(v) for v in _sub_dord_raw]

        n_gl  = len(gl_ids)
        n_sub = len(sub_ids)

        # Index-based availability sets: O(1) discard vs. O(n) list rebuild.
        avail_gl_idx  = set(range(n_gl))
        avail_sub_idx = set(range(n_sub))

        for sub_i in range(n_sub):
            if sub_i not in avail_sub_idx:
                continue

            sub_id     = sub_ids[sub_i]
            sub_amount = sub_amts[sub_i]
            sub_dord   = sub_dords[sub_i]
            sub_vn     = sub_vns[sub_i]

            # Pre-filter GL candidates by date tolerance (reduces combination space).
            candidates = [
                i for i in avail_gl_idx
                if gl_dords[i] is not None and sub_dord is not None
                and abs(gl_dords[i] - sub_dord) <= DATE_TOLERANCE_DAYS
            ]
            if len(candidates) < 2:
                continue

            # Infeasibility guard: even using ALL date-filtered GL records, can we
            # reach sub_amount within tolerance? (Assumes positive amounts.)
            if sub_amount > 0:
                max_reachable = sum(gl_amts[i] for i in candidates)
                base_max = max(abs(max_reachable), abs(sub_amount), 0.01)
                if max_reachable < sub_amount - max(AMOUNT_PCT_TOLERANCE * base_max, AMOUNT_ABS_TOLERANCE):
                    continue

            # Sort descending by amount: find amount-feasible combos with fewer iterations.
            candidates_sorted = sorted(candidates, key=lambda i: -gl_amts[i])

            best_match: Optional[Tuple[float, tuple, Dict]] = None

            for size in range(2, MAX_GROUP_SIZE + 1):
                if len(candidates_sorted) < size:
                    break
                for combo in combinations(candidates_sorted, size):
                    combos_evaluated += 1
                    gl_sum = sum(gl_amts[i] for i in combo)
                    base   = max(abs(gl_sum), abs(sub_amount), 0.01)
                    if abs(gl_sum - sub_amount) > max(AMOUNT_PCT_TOLERANCE * base, AMOUNT_ABS_TOLERANCE):
                        continue
                    # Date already pre-filtered; compute group-level similarity.
                    indiv_vendor = [_vendor_sim(gl_vns[i], sub_vn) for i in combo]
                    indiv_date   = [_date_sim_ordinals(gl_dords[i], sub_dord) for i in combo]
                    comp = {
                        "vendor_similarity": sum(indiv_vendor) / len(indiv_vendor),
                        "amount_similarity": _amount_sim(gl_sum, sub_amount),
                        "date_similarity":   sum(indiv_date)   / len(indiv_date),
                        "entity_similarity": 1.0,
                    }
                    sim = _final_sim(comp, weights)
                    if sim >= threshold:
                        if best_match is None or sim > best_match[0]:
                            best_match = (sim, combo, comp)

                if best_match is not None:
                    max_depth_reached = max(max_depth_reached, size)

            if best_match is not None:
                sim, combo, comp = best_match
                gl_combo_ids = [gl_ids[i] for i in combo]
                avail_sub_idx.discard(sub_i)
                for idx in combo:
                    avail_gl_idx.discard(idx)
                used_sub.add(sub_id)
                used_gl.update(gl_combo_ids)
                matches.append(ProbabilisticMatchRecord(
                    match_id=         str(uuid.uuid4()),
                    record_ids_A=     gl_combo_ids,
                    record_ids_B=     [sub_id],
                    final_similarity= round(sim, 4),
                    component_scores= {k: round(v, 4) for k, v in comp.items()},
                    grouping_type=    "many_to_one",
                ))

    return matches, used_gl, used_sub, combos_evaluated, max_depth_reached


# ---------------------------------------------------------------------------
# Step 3 — 1:N grouping
# ---------------------------------------------------------------------------

def _match_1_to_n(
    gl_pool: pd.DataFrame,
    sub_pool: pd.DataFrame,
    threshold: float,
    weights: Dict[str, float],
) -> Tuple[List[ProbabilisticMatchRecord], Set[str], Set[str], int, int]:
    """
    For each entity group: search combinations of 2–MAX_GROUP_SIZE Sub rows
    whose total amount is within the GL's tolerance band.
    Accepts if group-level final_similarity ≥ threshold.

    Same optimisation strategy as _match_n_to_1 (symmetric mirror).

    Returns:
        (matches, used_gl_ids, used_sub_ids, combos_evaluated, max_depth_reached)
    """
    if gl_pool.empty or sub_pool.empty:
        return [], set(), set(), 0, 0

    matches:  List[ProbabilisticMatchRecord] = []
    used_gl:  Set[str] = set()
    used_sub: Set[str] = set()
    combos_evaluated  = 0
    max_depth_reached = 0

    entities = sorted(
        set(gl_pool["entity"].dropna().unique()) &
        set(sub_pool["entity"].dropna().unique())
    )

    for entity in entities:
        gl_e  = gl_pool[gl_pool["entity"] == entity]
        sub_e = sub_pool[sub_pool["entity"] == entity]

        if gl_e.empty or sub_e.empty:
            continue

        gl_ids  = gl_e["gl_id"].astype(str).tolist()
        gl_amts = gl_e["amount"].astype(float).tolist()
        gl_vns  = gl_e["Vendor_Normalized"].astype(str).tolist()
        _gl_dord_raw = (pd.to_datetime(gl_e["transaction_date"], errors="coerce") - _EPOCH).dt.days
        gl_dords = [None if pd.isna(v) else int(v) for v in _gl_dord_raw]

        sub_ids   = sub_e["subledger_id"].astype(str).tolist()
        sub_amts  = sub_e["amount"].astype(float).tolist()
        sub_vns   = sub_e["Vendor_Normalized"].astype(str).tolist()
        _sub_dord_raw = (pd.to_datetime(sub_e["transaction_date"], errors="coerce") - _EPOCH).dt.days
        sub_dords = [None if pd.isna(v) else int(v) for v in _sub_dord_raw]

        n_gl  = len(gl_ids)
        n_sub = len(sub_ids)

        avail_gl_idx  = set(range(n_gl))
        avail_sub_idx = set(range(n_sub))

        for gl_i in range(n_gl):
            if gl_i not in avail_gl_idx:
                continue

            gl_id     = gl_ids[gl_i]
            gl_amount = gl_amts[gl_i]
            gl_dord   = gl_dords[gl_i]
            gl_vn     = gl_vns[gl_i]

            # Pre-filter Sub candidates by date tolerance.
            candidates = [
                i for i in avail_sub_idx
                if sub_dords[i] is not None and gl_dord is not None
                and abs(sub_dords[i] - gl_dord) <= DATE_TOLERANCE_DAYS
            ]
            if len(candidates) < 2:
                continue

            # Infeasibility guard (assumes positive amounts).
            if gl_amount > 0:
                max_reachable = sum(sub_amts[i] for i in candidates)
                base_max = max(abs(max_reachable), abs(gl_amount), 0.01)
                if max_reachable < gl_amount - max(AMOUNT_PCT_TOLERANCE * base_max, AMOUNT_ABS_TOLERANCE):
                    continue

            candidates_sorted = sorted(candidates, key=lambda i: -sub_amts[i])

            best_match: Optional[Tuple[float, tuple, Dict]] = None

            for size in range(2, MAX_GROUP_SIZE + 1):
                if len(candidates_sorted) < size:
                    break
                for combo in combinations(candidates_sorted, size):
                    combos_evaluated += 1
                    sub_sum = sum(sub_amts[i] for i in combo)
                    base    = max(abs(gl_amount), abs(sub_sum), 0.01)
                    if abs(gl_amount - sub_sum) > max(AMOUNT_PCT_TOLERANCE * base, AMOUNT_ABS_TOLERANCE):
                        continue
                    indiv_vendor = [_vendor_sim(gl_vn, sub_vns[i]) for i in combo]
                    indiv_date   = [_date_sim_ordinals(gl_dord, sub_dords[i]) for i in combo]
                    comp = {
                        "vendor_similarity": sum(indiv_vendor) / len(indiv_vendor),
                        "amount_similarity": _amount_sim(gl_amount, sub_sum),
                        "date_similarity":   sum(indiv_date)   / len(indiv_date),
                        "entity_similarity": 1.0,
                    }
                    sim = _final_sim(comp, weights)
                    if sim >= threshold:
                        if best_match is None or sim > best_match[0]:
                            best_match = (sim, combo, comp)

                if best_match is not None:
                    max_depth_reached = max(max_depth_reached, size)

            if best_match is not None:
                sim, combo, comp = best_match
                sub_combo_ids = [sub_ids[i] for i in combo]
                avail_gl_idx.discard(gl_i)
                for idx in combo:
                    avail_sub_idx.discard(idx)
                used_gl.add(gl_id)
                used_sub.update(sub_combo_ids)
                matches.append(ProbabilisticMatchRecord(
                    match_id=         str(uuid.uuid4()),
                    record_ids_A=     [gl_id],
                    record_ids_B=     sub_combo_ids,
                    final_similarity= round(sim, 4),
                    component_scores= {k: round(v, 4) for k, v in comp.items()},
                    grouping_type=    "one_to_many",
                ))

    return matches, used_gl, used_sub, combos_evaluated, max_depth_reached


# ---------------------------------------------------------------------------
# Pool filter (reuse pattern from deterministic matching)
# ---------------------------------------------------------------------------

def _filter_pool(df: pd.DataFrame, id_col: str, used_ids: Set[str]) -> pd.DataFrame:
    """Return rows of *df* whose *id_col* is not in *used_ids*. Safe for empty DataFrames."""
    if df.empty or id_col not in df.columns:
        return df
    return df[~df[id_col].astype(str).isin(used_ids)]


# ---------------------------------------------------------------------------
# Main pipeline entry point
# ---------------------------------------------------------------------------

def run_probabilistic_matching(
    gl_pool:   pd.DataFrame,
    sub_pool:  pd.DataFrame,
    threshold: float = DEFAULT_THRESHOLD,
    weights:   Optional[Dict[str, float]] = None,
) -> ProbabilisticResult:
    """
    Run the 3-step probabilistic matching pipeline on the residual pool.

    Args:
        gl_pool:   GL residual DataFrame — must contain:
                     gl_id, Vendor_Normalized, amount, transaction_date, entity
        sub_pool:  Subledger residual DataFrame — must contain:
                     subledger_id, Vendor_Normalized, amount, transaction_date, entity
        threshold: Minimum final_similarity for a match to be accepted (0.0–1.0).
        weights:   Override default component weights. Defaults to DEFAULT_WEIGHTS.

    Returns:
        ProbabilisticResult — matches, updated residual pools, and metadata.

    Raises:
        ValueError — if a required column is missing from a non-empty DataFrame.
    """
    if weights is None:
        weights = DEFAULT_WEIGHTS

    _required_gl  = {"gl_id", "Vendor_Normalized", "amount", "transaction_date", "entity"}
    _required_sub = {"subledger_id", "Vendor_Normalized", "amount", "transaction_date", "entity"}

    if len(gl_pool) > 0:
        missing_gl = _required_gl - set(gl_pool.columns)
        if missing_gl:
            raise ValueError(f"GL pool missing required columns: {missing_gl}")
    if len(sub_pool) > 0:
        missing_sub = _required_sub - set(sub_pool.columns)
        if missing_sub:
            raise ValueError(f"Sub pool missing required columns: {missing_sub}")

    t_total = time.perf_counter()
    logger.info(
        "Probabilistic matching started: GL=%d rows, Sub=%d rows, threshold=%.2f",
        len(gl_pool), len(sub_pool), threshold,
    )

    all_used_gl:  Set[str] = set()
    all_used_sub: Set[str] = set()
    all_matches:  List[ProbabilisticMatchRecord] = []

    # Step 1 — 1:1 matching
    gl_rem  = _filter_pool(gl_pool,  "gl_id",        all_used_gl)
    sub_rem = _filter_pool(sub_pool, "subledger_id", all_used_sub)
    logger.info("Step 1 (1:1) starting: GL pool=%d, Sub pool=%d", len(gl_rem), len(sub_rem))
    t0 = time.perf_counter()
    m1, g1, s1, comparisons_1 = _match_1to1(gl_rem, sub_rem, threshold, weights)
    elapsed_1 = time.perf_counter() - t0
    logger.info(
        "Step 1 (1:1) complete: matches=%d, candidate_pairs_after_blocking=%d, elapsed=%.3fs",
        len(m1), comparisons_1, elapsed_1,
    )
    all_matches.extend(m1)
    all_used_gl.update(g1)
    all_used_sub.update(s1)

    # Step 2 — N:1 grouping
    gl_rem  = _filter_pool(gl_pool,  "gl_id",        all_used_gl)
    sub_rem = _filter_pool(sub_pool, "subledger_id", all_used_sub)
    logger.info("Step 2 (N:1) starting: GL pool=%d, Sub pool=%d", len(gl_rem), len(sub_rem))
    t0 = time.perf_counter()
    m2, g2, s2, combos_2, max_depth_2 = _match_n_to_1(gl_rem, sub_rem, threshold, weights)
    elapsed_2 = time.perf_counter() - t0
    logger.info(
        "Step 2 (N:1) complete: matches=%d, combos_evaluated=%d, max_depth=%d, elapsed=%.3fs",
        len(m2), combos_2, max_depth_2, elapsed_2,
    )
    all_matches.extend(m2)
    all_used_gl.update(g2)
    all_used_sub.update(s2)

    # Step 3 — 1:N grouping
    gl_rem  = _filter_pool(gl_pool,  "gl_id",        all_used_gl)
    sub_rem = _filter_pool(sub_pool, "subledger_id", all_used_sub)
    logger.info("Step 3 (1:N) starting: GL pool=%d, Sub pool=%d", len(gl_rem), len(sub_rem))
    t0 = time.perf_counter()
    m3, g3, s3, combos_3, max_depth_3 = _match_1_to_n(gl_rem, sub_rem, threshold, weights)
    elapsed_3 = time.perf_counter() - t0
    logger.info(
        "Step 3 (1:N) complete: matches=%d, combos_evaluated=%d, max_depth=%d, elapsed=%.3fs",
        len(m3), combos_3, max_depth_3, elapsed_3,
    )
    all_matches.extend(m3)
    all_used_gl.update(g3)
    all_used_sub.update(s3)

    residual_gl  = _filter_pool(gl_pool,  "gl_id",        all_used_gl).copy()
    residual_sub = _filter_pool(sub_pool, "subledger_id", all_used_sub).copy()

    total_elapsed = time.perf_counter() - t_total
    logger.info(
        "Probabilistic matching complete: total_matches=%d, residual_gl=%d, residual_sub=%d, "
        "step1_comparisons=%d, total_combos=%d, max_depth=%d, total_elapsed=%.3fs",
        len(all_matches),
        len(residual_gl), len(residual_sub),
        comparisons_1,
        combos_2 + combos_3,
        max(max_depth_2, max_depth_3, 0),
        total_elapsed,
    )

    return ProbabilisticResult(
        matches=        all_matches,
        residual_gl=    residual_gl,
        residual_sub=   residual_sub,
        total_gl=       len(gl_pool),
        total_sub=      len(sub_pool),
        threshold_used= threshold,
        weights_used=   weights,
    )
