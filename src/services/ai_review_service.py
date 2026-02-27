"""
AI Review Service — Phase 6A: ai_suggested → ai_review_complete

Pure function that applies human review decisions to the AI suggestion list.

Behaviour:
  - "accepted"  → user_status set to "accepted"; match moves to the FINAL bucket;
                   GL and Sub records REMOVED from the residual pool (now matched).
  - "rejected"  → user_status set to "rejected"; match moves to rejected bucket;
                   GL and Sub records REMAIN in the residual pool (unchanged).
  - No decision → match remains in ai_suggested bucket with user_status="pending";
                   GL and Sub records remain in the residual pool (unchanged).

Key distinction from probabilistic review (Phase 5A):
  Phase 5A — probabilistic matching CONSUMES records from the residual.
             Review-accepted: records already gone from residual (no change needed).
             Review-rejected: records must be RETURNED to residual from clean_data.

  Phase 6A — AI matching is ADVISORY; residual pool is never mutated during Phase 6.
             Review-accepted: records must be REMOVED from residual (now matched).
             Review-rejected: records already in residual (no change needed).

No computation is performed; this is a bookkeeping step only.
"""

from dataclasses import dataclass
from typing import Dict, List, Set

import pandas as pd


@dataclass
class AIReviewResult:
    """Output of process_ai_review()."""
    accepted_matches:     List[dict]   # moved to runtime["matching"]["final"]
    rejected_matches:     List[dict]   # appended to runtime["matching"]["rejected"]
    pending_matches:      List[dict]   # stays in runtime["matching"]["ai_suggested"]
    updated_residual_gl:  pd.DataFrame
    updated_residual_sub: pd.DataFrame

    @property
    def accepted_count(self) -> int:
        return len(self.accepted_matches)

    @property
    def rejected_count(self) -> int:
        return len(self.rejected_matches)

    def remaining_ai_suggested(self) -> List[dict]:
        """Only pending matches stay in the ai_suggested bucket after review."""
        return self.pending_matches


def process_ai_review(
    decisions:            List[dict],       # [{"match_id": str, "decision": "accepted"|"rejected"}]
    ai_matches:           List[dict],       # runtime["matching"]["ai_suggested"]
    current_residual_gl:  pd.DataFrame,    # runtime["residual_pool"]["gl"]
    current_residual_sub: pd.DataFrame,    # runtime["residual_pool"]["subledger"]
    clean_gl:             pd.DataFrame,    # runtime["clean_data"]["gl"] (unused — reserved for interface consistency)
    clean_sub:            pd.DataFrame,    # runtime["clean_data"]["subledger"] (unused — reserved for interface consistency)
) -> AIReviewResult:
    """
    Apply review decisions to the AI suggestion list.

    Args:
        decisions:            List of {match_id, decision} dicts.
        ai_matches:           Current AI suggestion list (list of dicts).
        current_residual_gl:  Existing residual GL pool (DataFrame).
        current_residual_sub: Existing residual Sub pool (DataFrame).
        clean_gl:             Full clean GL DataFrame (reserved — not used in Phase 6A).
        clean_sub:            Full clean Sub DataFrame (reserved — not used in Phase 6A).

    Returns:
        AIReviewResult with classified matches and updated residual pools.
        - Accepted records are removed from the residual (they are now matched).
        - Rejected / pending records remain in the residual unchanged.

    Raises:
        ValueError: if any match_id in decisions does not exist in ai_matches.
    """
    # Build decision lookup: match_id → "accepted" | "rejected"
    decision_map: Dict[str, str] = {}
    for d in decisions:
        decision_map[d["match_id"]] = d["decision"]

    # Validate: every supplied match_id must exist in the AI suggestion list
    existing_ids: Set[str] = {m["match_id"] for m in ai_matches}
    unknown = set(decision_map.keys()) - existing_ids
    if unknown:
        raise ValueError(
            f"Unknown match_id(s) in decisions: {sorted(unknown)}. "
            "Only AI suggestion match IDs are valid."
        )

    accepted:         List[dict] = []
    rejected:         List[dict] = []
    pending:          List[dict] = []
    accepted_gl_ids:  List[str]  = []  # records to REMOVE from residual (now matched)
    accepted_sub_ids: List[str]  = []  # records to REMOVE from residual (now matched)

    for match in ai_matches:
        mid      = match["match_id"]
        decision = decision_map.get(mid)

        if decision == "accepted":
            accepted.append({**match, "user_status": "accepted"})
            # These records are now matched → remove from residual
            accepted_gl_ids.extend(match.get("record_ids_A", []))
            accepted_sub_ids.extend(match.get("record_ids_B", []))

        elif decision == "rejected":
            rejected.append({**match, "user_status": "rejected"})
            # Records remain in the residual pool — no action required.

        else:
            # No decision supplied — leave as-is
            pending.append(match)

    # ---------------------------------------------------------------------------
    # Remove accepted records from the residual pool.
    # Rejected / pending records are already in the residual and stay there.
    # ---------------------------------------------------------------------------
    if accepted_gl_ids and not current_residual_gl.empty and "gl_id" in current_residual_gl.columns:
        mask       = ~current_residual_gl["gl_id"].astype(str).isin(accepted_gl_ids)
        updated_gl = current_residual_gl[mask].copy().reset_index(drop=True)
    else:
        updated_gl = current_residual_gl

    if accepted_sub_ids and not current_residual_sub.empty and "subledger_id" in current_residual_sub.columns:
        mask        = ~current_residual_sub["subledger_id"].astype(str).isin(accepted_sub_ids)
        updated_sub = current_residual_sub[mask].copy().reset_index(drop=True)
    else:
        updated_sub = current_residual_sub

    return AIReviewResult(
        accepted_matches=     accepted,
        rejected_matches=     rejected,
        pending_matches=      pending,
        updated_residual_gl=  updated_gl,
        updated_residual_sub= updated_sub,
    )
