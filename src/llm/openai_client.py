import os
import json
from typing import Any, Dict, List
from openai import OpenAI


# Same model GetPolitical uses. Override per deployment with OPENAI_MODEL, or
# per session via config["ai_model"] (passed as OpenAIClient(model=...)).
DEFAULT_MODEL = os.getenv("OPENAI_MODEL", "gpt-5.6-luna")

# gpt-5.6 models are reasoning models: hidden reasoning tokens count against
# max_completion_tokens, so small caps (e.g. 512) come back empty.
MIN_COMPLETION_TOKENS = 4000


class OpenAIClient:
    """
    Central client for all OpenAI LLM interactions in the system.
    Mirrors the functionality of the previous Anthropic client gateway.

    gpt-5.6 models reject `temperature` and `max_tokens`; the `temperature`
    arguments below are accepted for caller compatibility but not sent.
    """

    def __init__(self, model: str | None = None):
        api_key = os.getenv("OPENAI_API_KEY")

        if not api_key:
            raise ValueError(
                "OPENAI_API_KEY not found in environment variables."
            )

        self.client = OpenAI(api_key=api_key)
        self.model = model or DEFAULT_MODEL

    def _complete(self, messages: List[Dict[str, str]], max_tokens: int, json_mode: bool) -> str:
        kwargs: Dict[str, Any] = {}
        if json_mode:
            kwargs["response_format"] = {"type": "json_object"}
        response = self.client.chat.completions.create(
            model=self.model,
            messages=messages,
            max_completion_tokens=max(max_tokens, MIN_COMPLETION_TOKENS),
            **kwargs,
        )
        choice = response.choices[0]
        text = (choice.message.content or "").strip()
        if choice.finish_reason == "length" or not text:
            raise ValueError(f"Model output cut off or empty (finish_reason={choice.finish_reason})")
        return text

    @staticmethod
    def _parse_json(text: str) -> Dict[str, Any]:
        if text.startswith("```"):
            text = text.strip("`").removeprefix("json").strip()
        return json.loads(text)

    def generate_json(
        self,
        system_prompt: str,
        user_prompt: str,
        temperature: float = 0,
        max_tokens: int = 4096,
    ) -> Dict[str, Any]:
        """
        Generate structured JSON output from OpenAI.
        """
        text_output = self._complete(
            [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            max_tokens,
            json_mode=True,
        )

        try:
            return self._parse_json(text_output)
        except json.JSONDecodeError:
            raise ValueError(
                f"Model did not return valid JSON:\n{text_output}"
            )

    def generate_text(
        self,
        system_prompt: str,
        user_prompt: str,
        temperature: float = 0,
        max_tokens: int = 1024,
    ) -> str:
        """
        Generate plain text output from OpenAI.
        """
        return self._complete(
            [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            max_tokens,
            json_mode=False,
        )

    def generate_with_history(
        self,
        system_prompt: str,
        messages: List[Dict[str, str]],
        temperature: float = 0.3,
        max_tokens: int = 2048,
    ) -> str:
        """
        Generate a reply given a full conversation history.

        `messages` is a list of {"role": "user"|"assistant", "content": "..."} dicts.
        The system prompt is prepended automatically.
        """
        full_messages = [{"role": "system", "content": system_prompt}] + messages
        return self._complete(full_messages, max_tokens, json_mode=False)

    def generate_with_history_json(
        self,
        system_prompt: str,
        messages: List[Dict[str, str]],
        temperature: float = 0.3,
        max_tokens: int = 2048,
    ) -> Dict[str, Any]:
        """
        Generate a structured JSON reply given a full conversation history.
        Uses response_format json_object to guarantee valid JSON output.
        `messages` is a list of {"role": "user"|"assistant", "content": "..."} dicts.
        The system prompt is prepended automatically.
        """
        full_messages = [{"role": "system", "content": system_prompt}] + messages
        text = self._complete(full_messages, max_tokens, json_mode=True)
        try:
            return self._parse_json(text)
        except json.JSONDecodeError:
            return {"reply": text, "config_update": None}
