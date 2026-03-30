"""Pydantic v2 schemas for AI-suggested matching configuration."""

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, field_validator

from src.schemas.intake import SnapshotInfo


class DeterministicScenarioConfig(BaseModel):
    scenario_id:           int
    description:           str
    match_fields:          List[str]        # roles: ["vendor", "amount", "date", "entity"]
    date_tolerance_days:   Optional[int] = None   # None/0 = exact date match required
    amount_tolerance_abs:  Optional[float] = None  # None/0 = exact amount match
    amount_tolerance_pct:  Optional[float] = None  # None/0 = exact amount match
    confidence_score:      float


class ProbabilisticConfig(BaseModel):
    weights:               Dict[str, float]  # {"vendor": 0.45, "amount": 0.40, "date": 0.15}
    threshold:             float
    date_tolerance_days:   int
    amount_pct_tolerance:  float
    amount_abs_tolerance:  float

    @field_validator("weights")
    @classmethod
    def weights_sum_to_one(cls, v: Dict[str, float]) -> Dict[str, float]:
        total = sum(v.values())
        if abs(total - 1.0) > 0.01:
            raise ValueError(f"Probabilistic weights must sum to 1.0 (got {total:.4f})")
        return v

    @field_validator("threshold")
    @classmethod
    def threshold_in_range(cls, v: float) -> float:
        if not (0.0 <= v <= 1.0):
            raise ValueError(f"Threshold must be between 0.0 and 1.0 (got {v})")
        return v


class SuggestMatchingConfigResponse(BaseModel):
    session_id:               str
    state:                    str
    deterministic_scenarios:  List[DeterministicScenarioConfig]
    probabilistic:            ProbabilisticConfig
    rationale:                str     # AI narrative explaining recommendations


class ConfirmMatchingConfigRequest(BaseModel):
    deterministic: List[DeterministicScenarioConfig]
    probabilistic: ProbabilisticConfig


class ConfirmMatchingConfigResponse(BaseModel):
    session_id:     str
    state:          str
    matching_config: Dict[str, Any]
    snapshot:       SnapshotInfo
