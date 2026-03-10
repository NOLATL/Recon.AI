import os
import json
from typing import Dict, Any
from openai import OpenAI


class OpenAIClient:
    """
    Central client for all OpenAI LLM interactions in the system.
    Mirrors the functionality of the previous Anthropic client gateway.
    """

    def __init__(self, model: str = "gpt-4.1"):
        api_key = os.getenv("OPENAI_API_KEY")

        if not api_key:
            raise ValueError(
                "OPENAI_API_KEY not found in environment variables."
            )

        self.client = OpenAI(api_key=api_key)
        self.model = model

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

        response = self.client.chat.completions.create(
            model=self.model,
            temperature=temperature,
            max_tokens=max_tokens,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ]
        )

        text_output = response.choices[0].message.content or ""

        try:
            return json.loads(text_output)
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
        response = self.client.chat.completions.create(
            model=self.model,
            temperature=temperature,
            max_tokens=max_tokens,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ]
        )
        return (response.choices[0].message.content or "").strip()
