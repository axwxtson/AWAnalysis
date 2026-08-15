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

from collections.abc import Callable
from typing import Any, TypeVar

import anthropic

from aw_analysis.client.retry import (
    NO_RETRY,
    RetryPolicy,
    compute_delay,
    retry_after_seconds,
)
from aw_analysis.config import ModelConfig, get_settings

T = TypeVar("T")


class AnthropicClient:
    """Synchronous wrapper around anthropic.Anthropic.

    All model calls in the agent go through this class. Keeping the
    SDK behind one wrapper means Stage 7 can add provider abstraction
    in one file rather than dozens.
    """

    def __init__(self, *, policy: RetryPolicy | None = None) -> None:
        # max_retries=0 disables the SDK's own retry loop. anthropic
        # 0.107.1 defaults it to 2, so leaving it unset stacks the
        # SDK's jittered backoff underneath ours: up to three SDK
        # calls per attempt of ours, and the eval runner's loop on
        # top of that again. Retry is owned in this class or nowhere.
        self._sdk = anthropic.Anthropic(
            api_key=get_settings().anthropic_api_key,
            max_retries=0,
        )
        self._policy = policy or RetryPolicy()

    def _with_retry(
        self,
        call: Callable[[], T],
        *,
        policy: RetryPolicy | None = None,
    ) -> T:
        """Run `call`, retrying transient API failures per policy.

        Catches anthropic.APIError, the root of the SDK's hierarchy,
        rather than Exception. A TypeError from argument construction
        is our bug and must surface on the first attempt rather than
        being retried three times.

        Server advice is a floor and the policy cap is a ceiling. The
        retry-after header is re-read from each fresh response, so a
        long first wait shortens as the window drains.

        Fail-fast uses the *remaining* sleep budget, not the total. At
        the last attempt only one sleep remains, so advice of 30s
        against a 15s cap is unreachable and sleeping into it pays the
        full latency to surface the same error. Re-raising is bare, so
        the caller still receives the original typed exception with
        the header intact.
        """
        active = policy or self._policy
        for attempt in range(1, active.max_attempts + 1):
            try:
                return call()
            except anthropic.APIError as exc:
                if attempt == active.max_attempts or not active.classify(exc):
                    raise
                wait = compute_delay(attempt, active)
                advised = retry_after_seconds(exc)
                if advised is not None:
                    remaining = (active.max_attempts - attempt) * active.max_delay
                    if advised > remaining:
                        raise
                    wait = min(active.max_delay, max(wait, advised))
                active.sleep(wait)
        raise RuntimeError("unreachable: RetryPolicy validates max_attempts >= 1")
        
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
        return self._with_retry(lambda: self._sdk.messages.create(**kwargs))
        
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
        response = self._with_retry(
            lambda: self._sdk.messages.count_tokens(**kwargs),
            policy=NO_RETRY,
        )
        return int(response.input_tokens)