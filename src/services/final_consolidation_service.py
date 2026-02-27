"""
Final Consolidation Service — Phase 7: ai_review_complete → final_consolidated

Pure function that assembles the complete final reconciliation dataset.

Inputs (all read-only):
  - Deterministic match list  — all auto_confirmed matches
  - Probabilistic match list  — filters to user_status == "accepted" only
  - Final bucket              — AI-accepted matches placed here by Phase 6A
  - Rejected match list       — all explicitly rejected matches (Phases 5A + 6A)
  - Residual pool             — GL and Sub records unmatched after all phases

Output (FinalConsolidationResult):
  - all_matches: complete list = deterministic + accepted_prob + ai_final
  - Counts per layer and totals
  - Residual counts
  - Rejected count
  - Override count (v1: always 0 — no override mechanism exists)

No computation is performed. This is a pure bookkeeping assembly step.

Layer hierarchy (authoritative → additive → advisory):
  1. Deterministic — authoritative; all included regardless of user_status
  2. Probabilistic — additive; only user_status == "accepted" included
  3. AI Final     — advisory confirmed; only matches already in final bucket
                    (accepted in Phase 6A; pending/rejected excluded)
"""

from dataclasses import dataclass
from typing import List

import pandas as pd


@dataclass
class FinalConsolidationResult:
    """Output of run_final_consolidation()."""
    all_matches:               List[dict]  # complete consolidated final list
    deterministic_match_count: int
    probabilistic_match_count: int  # accepted only
    ai_match_count:            int  # accepted only (from final bucket)
    total_match_count:         int
    residual_gl_count:         int
    residual_sub_count:        int
    rejected_count:            int
    override_count:            int


def run_final_consolidation(
    det_matches:  List[dict],      # runtime["matching"]["deterministic"]
    prob_matches: List[dict],      # runtime["matching"]["probabilistic"]
    ai_final:     List[dict],      # runtime["matching"]["final"] (Phase 6A accepted)
    rejected:     List[dict],      # runtime["matching"]["rejected"]
    residual_gl:  pd.DataFrame,    # runtime["residual_pool"]["gl"]
    residual_sub: pd.DataFrame,    # runtime["residual_pool"]["subledger"]
) -> FinalConsolidationResult:
    """
    Assemble the final reconciliation dataset from all matching layers.

    Args:
        det_matches:  All deterministic matches (user_status="auto_confirmed").
        prob_matches: All probabilistic matches (filters to accepted only).
        ai_final:     AI matches already accepted and placed in final bucket by Phase 6A.
        rejected:     All rejected matches from any phase.
        residual_gl:  Unmatched GL records remaining after all phases.
        residual_sub: Unmatched Sub records remaining after all phases.

    Returns:
        FinalConsolidationResult with assembled match list and summary counts.
    """
    # Layer 1: all deterministic (authoritative, immutable)
    det_list = list(det_matches)

    # Layer 2: accepted probabilistic only
    prob_accepted = [m for m in prob_matches if m.get("user_status") == "accepted"]

    # Layer 3: AI-accepted matches (already in final bucket from Phase 6A)
    ai_list = list(ai_final)

    # Build complete consolidated match list (preserves layer ordering)
    all_matches = det_list + prob_accepted + ai_list

    # Count overrides across all accepted matches
    override_count = sum(
        1 for m in all_matches if m.get("override_flag") is True
    )

    residual_gl_count  = len(residual_gl)  if residual_gl  is not None else 0
    residual_sub_count = len(residual_sub) if residual_sub is not None else 0

    return FinalConsolidationResult(
        all_matches=               all_matches,
        deterministic_match_count= len(det_list),
        probabilistic_match_count= len(prob_accepted),
        ai_match_count=            len(ai_list),
        total_match_count=         len(all_matches),
        residual_gl_count=         residual_gl_count,
        residual_sub_count=        residual_sub_count,
        rejected_count=            len(rejected),
        override_count=            override_count,
    )
