# aw_analysis/client/anthropic_client.py
"""Thin wrapper around the Anthropic SDK.

Stage 5 changes:
  - create() now accepts a ModelConfig instead of bare model/temperature/
    max_tokens kwargs. Callers must pass a config; this is the
    single point where Module 5's per-task tuning lands at the SDK.
  - count_tokens() exposes the official endpoint, which is the only
    correct way to estimate token cost for Claude (see Module 5
    Exercise 5.1: the 4:1 rule under-counts by ~20%).
"""
from __future__ import annotations

from typing import Any

import anthropic

from aw_analysis.config import SETTINGS, ModelConfig


class AnthropicClient:
    """Synchronous wrapper around anthropic.Anthropic.

    All model calls in the agent go through this class. Keeping the
    SDK behind one wrapper means Stage 7 can add provider abstraction
    in one file rather than dozens.
    """

    def __init__(self) -> None:
        self._sdk = anthropic.Anthropic(api_key=SETTINGS.anthropic_api_key)

    def create(
        self,
        *,
        config: ModelConfig,
        system: str | list[dict[str, Any]],
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        tool_choice: dict[str, Any] | None = None,
    ) -> Any:
        """Create a single message with the given ModelConfig.

        Note that we pass the SDK named arguments only; positional
        is brittle across SDK versions.

        tool_choice, when set, forces the model's tool use for this call
        (e.g. {"type": "tool", "name": "get_equity_price"}). The agent
        loop only forces on the first tool-selection iteration; later
        iterations leave it None so the model can synthesise an answer.
        """
        kwargs: dict[str, Any] = {
            "model": config.model,
            "max_tokens": config.max_tokens,
            "temperature": config.temperature,
            "system": system,
            "messages": messages,
        }
        if tools is not None:
            kwargs["tools"] = tools
        if tool_choice is not None:
            kwargs["tool_choice"] = tool_choice
        return self._sdk.messages.create(**kwargs)
        
    def count_tokens(
        self,
        *,
        model: str,
        system: str | list[dict[str, Any]],
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
    ) -> int:
        """Return the input-token count for the given message set.

        Uses Anthropic's count_tokens endpoint — the ground truth.
        Used by the Conversation soft-budget guard. Do not estimate
        with character heuristics; Module 5 Ex 5.1 showed the 4:1
        rule undercounts by ~20% and dense numerical content makes
        it worse.
        """
        kwargs: dict[str, Any] = {
            "model": model,
            "system": system,
            "messages": messages,
        }
        if tools is not None:
            kwargs["tools"] = tools
        response = self._sdk.messages.count_tokens(**kwargs)
        return int(response.input_tokens)