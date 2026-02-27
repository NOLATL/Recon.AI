"""
Probabilistic Review Service — Phase 5A: probabilistic_complete → probabilistic_review_complete

Pure function that applies human review decisions to the probabilistic match list.

Behaviour:
  - "accepted"  → user_status set to "accepted"; match remains in probabilistic bucket.
  - "rejected"  → user_status set to "rejected"; match moves to rejected bucket;
                   GL and Sub records are returned to the residual pool.
  - No decision → match remains in probabilistic bucket with user_status="pending".

No computation is performed; this is a bookkeeping step only.

Rejected-record recovery:
  Records are retrieved from clean_data (never mutated) so the full row
  data (Vendor_Normalized, amount, date, entity) is always available.
"""

from dataclasses import dataclass, field
from typing import Dict, List, Set

import pandas as pd


@dataclass
class ProbabilisticReviewResult:
    """Output of process_probabilistic_review()."""
    accepted_matches:    List[dict]   # stays in runtime["matching"]["probabilistic"]
    rejected_matches:    List[dict]   # appended to runtime["matching"]["rejected"]
    pending_matches:     List[dict]   # no decision supplied; stays in probabilistic
    updated_residual_gl:  pd.DataFrame
    updated_residual_sub: pd.DataFrame

    @property
    def accepted_count(self) -> int:
        return len(self.accepted_matches)

    @property
    def rejected_count(self) -> int:
        return len(self.rejected_matches)

    def remaining_probabilistic(self) -> List[dict]:
        """Accepted + still-pending matches that stay in the probabilistic bucket."""
        return self.accepted_matches + self.pending_matches


def process_probabilistic_review(
    decisions:           List[dict],        # [{"match_id": str, "decision": "accepted"|"rejected"}]
    prob_matches:        List[dict],        # runtime["matching"]["probabilistic"]
    current_residual_gl:  pd.DataFrame,    # runtime["residual_pool"]["gl"]
    current_residual_sub: pd.DataFrame,    # runtime["residual_pool"]["subledger"]
    clean_gl:            pd.DataFrame,     # runtime["clean_data"]["gl"]
    clean_sub:           pd.DataFrame,     # runtime["clean_data"]["subledger"]
) -> ProbabilisticReviewResult:
    """
    Apply review decisions to the probabilistic match list.

    Args:
        decisions:           List of {match_id, decision} dicts.
        prob_matches:        Current probabilistic match list (list of dicts).
        current_residual_gl: Existing residual GL pool (DataFrame).
        current_residual_sub: Existing residual Sub pool (DataFrame).
        clean_gl:            Full clean GL DataFrame (source for returning records).
        clean_sub:           Full clean Sub DataFrame (source for returning records).

    Returns:
        ProbabilisticReviewResult with classified matches and updated residual pools.

    Raises:
        ValueError: if any match_id in decisions does not exist in prob_matches.
    """
    # Build decision lookup: match_id → "accepted" | "rejected"
    decision_map: Dict[str, str] = {}
    for d in decisions:
        decision_map[d["match_id"]] = d["decision"]

    # Validate: every supplied match_id must exist in the probabilistic list
    existing_ids: Set[str] = {m["match_id"] for m in prob_matches}
    unknown = set(decision_map.keys()) - existing_ids
    if unknown:
        raise ValueError(
            f"Unknown match_id(s) in decisions: {sorted(unknown)}. "
            "Only probabilistic match IDs are valid."
        )

    accepted:       List[dict] = []
    rejected:       List[dict] = []
    pending:        List[dict] = []
    returned_gl_ids:  List[str] = []
    returned_sub_ids: List[str] = []

    for match in prob_matches:
        mid      = match["match_id"]
        decision = decision_map.get(mid)

        if decision == "accepted":
            accepted.append({**match, "user_status": "accepted"})

        elif decision == "rejected":
            rejected.append({**match, "user_status": "rejected"})
            returned_gl_ids.extend(match.get("record_ids_A", []))
            returned_sub_ids.extend(match.get("record_ids_B", []))

        else:
            # No decision supplied — leave as-is
            pending.append(match)

    # ---------------------------------------------------------------------------
    # Recover rejected GL rows from clean_data
    # ---------------------------------------------------------------------------
    returned_gl = pd.DataFrame()
    if returned_gl_ids and not clean_gl.empty and "gl_id" in clean_gl.columns:
        mask        = clean_gl["gl_id"].astype(str).isin(returned_gl_ids)
        returned_gl = clean_gl[mask].copy()

    returned_sub = pd.DataFrame()
    if returned_sub_ids and not clean_sub.empty and "subledger_id" in clean_sub.columns:
        mask         = clean_sub["subledger_id"].astype(str).isin(returned_sub_ids)
        returned_sub = clean_sub[mask].copy()

    # ---------------------------------------------------------------------------
    # Merge recovered rows into the current residual pool (preserve existing rows)
    # ---------------------------------------------------------------------------
    if returned_gl.empty:
        updated_gl = current_residual_gl
    elif current_residual_gl.empty:
        updated_gl = returned_gl
    else:
        updated_gl = pd.concat([current_residual_gl, returned_gl], ignore_index=True)

    if returned_sub.empty:
        updated_sub = current_residual_sub
    elif current_residual_sub.empty:
        updated_sub = returned_sub
    else:
        updated_sub = pd.concat([current_residual_sub, returned_sub], ignore_index=True)

    return ProbabilisticReviewResult(
        accepted_matches=    accepted,
        rejected_matches=    rejected,
        pending_matches=     pending,
        updated_residual_gl=  updated_gl,
        updated_residual_sub= updated_sub,
    )
