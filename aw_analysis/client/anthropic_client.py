"""Thin wrapper around the Anthropic SDK.

Why wrap it? Three reasons:
1. We can swap the SDK or add retries/logging without touching agent code.
2. We centralise model defaults and the system prompt injection point.
3. It gives Stage 7 (multi-model orchestration) a single place to add routing.
"""

from __future__ import annotations

from typing import Any

from anthropic import Anthropic
from anthropic.types import Message, MessageParam, ToolParam

from aw_analysis.config import SETTINGS


class AnthropicClient:
    """Wrapper exposing a minimal surface we actually use."""

    def __init__(self, model: str | None = None) -> None:
        self._client = Anthropic(api_key=SETTINGS.anthropic_api_key)
        self.model = model or SETTINGS.default_model

    def create_message(
        self,
        messages: list[MessageParam],
        system: str,
        tools: list[ToolParam] | None = None,
        max_tokens: int = 2048,
        temperature: float = 1.0,
    ) -> Message:
        """Send a message to the model and return the full response."""
        kwargs: dict[str, Any] = {
            "model": self.model,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "system": system,
            "messages": messages,
        }
        if tools:
            kwargs["tools"] = tools

        return self._client.messages.create(**kwargs)