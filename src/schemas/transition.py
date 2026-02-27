"""Pydantic v2 schemas for state transition endpoints."""

from pydantic import BaseModel, Field


class TransitionRequest(BaseModel):
    triggered_by: str = Field(
        default="system",
        description="Identifier of the actor requesting the transition (user ID or 'system')",
    )


class TransitionResponse(BaseModel):
    session_id: str
    previous_state: str
    current_state: str
    snapshot_key: str = Field(
        description="Key under which the pre-transition snapshot was stored"
    )
