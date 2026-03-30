"""Pydantic v2 schemas for the general-purpose data exploration chat."""

from typing import Any, Dict, List, Optional

from pydantic import BaseModel


class ChatMessage(BaseModel):
    role:    str    # "user" | "assistant"
    content: str


class MatchingConfigUpdate(BaseModel):
    deterministic: Optional[List[Dict[str, Any]]] = None
    probabilistic: Optional[Dict[str, Any]] = None


class ChatRequest(BaseModel):
    message:              str
    conversation_history: List[ChatMessage] = []
    matching_context:     Optional[Dict[str, Any]] = None   # current proposed det+prob config


class ChatResponse(BaseModel):
    session_id:    str
    reply:         str
    rich_content:  Optional[Any] = None
    config_update: Optional[MatchingConfigUpdate] = None
