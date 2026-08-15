"""Retry policy and pure decision helpers for the Anthropic client.

Block 3. This module owns decisions only: what is retryable, how long
to wait, and what the server advised. The loop that applies them lands
in AnthropicClient in the next commit, which also disables the SDK's
built-in retry (max_retries=0) so the system has exactly one retry
layer. anthropic 0.107.1 defaults to max_retries=2 with jittered
exponential backoff capped at 8 seconds: no observability hook, no
injectable sleep, and a cap that cannot clear a per-minute rate
window.

Classification is by status code, not exception type. The SDK maps
529 to OverloadedError, which is unexported (it lives in
anthropic._exceptions) and does not subclass InternalServerError, so
a tuple of public exception types silently misses 529. Status codes
are stable across SDK upgrades; private class names are not.
"""
from __future__ import annotations

import random
import time
from collections.abc import Callable
from dataclasses import dataclass

import anthropic

# 408 request timeout, 409 lock conflict, 429 rate limit. 529
# (overloaded) needs no entry here: it satisfies >= 500 in
# is_retryable.
RETRYABLE_STATUS_CODES = frozenset({408, 409, 429})


def is_retryable(exc: Exception) -> bool:
    """Decide whether an exception is worth another attempt.

    Retryable: connection errors (APITimeoutError subclasses
    APIConnectionError, verified against anthropic 0.107.1) and
    status codes 408, 409, 429 and >= 500.

    Everything else fails immediately. 400 covers malformed requests
    and context overflow, both deterministic: retrying multiplies the
    cost of reaching the same error. Exceptions that are not the
    SDK's are our own bugs and must surface, not loop.
    """
    if isinstance(exc, anthropic.APIConnectionError):
        return True
    if isinstance(exc, anthropic.APIStatusError):
        return exc.status_code in RETRYABLE_STATUS_CODES or exc.status_code >= 500
    return False


def retry_after_seconds(exc: Exception) -> float | None:
    """Extract the server-advised wait in seconds, if present.

    Numeric form only. Anthropic sends integer seconds; the HTTP-date
    form is not parsed and falls back to computed backoff rather than
    carrying a date parser for a server that never sends one.
    """
    response = getattr(exc, "response", None)
    if response is None:
        return None
    raw = response.headers.get("retry-after")
    if raw is None:
        return None
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return None
    return value if value > 0 else None


@dataclass(frozen=True)
class RetryPolicy:
    """Retry behaviour, injected on AnthropicClient.

    Frozen because policies are values shared across call sites; the
    MODEL_CONFIG_REGISTRY swap-and-restore in orchestration is a
    lesson about shared mutable configuration, not a pattern to
    repeat.

    max_attempts counts total calls including the first, so
    max_attempts=1 disables retry. Worst-case sleep is bounded by
    (max_attempts - 1) * max_delay and is computable from the policy
    alone; entry points with a latency budget (the MCP server) size
    their policy from that bound.

    Defaults are the hot path: nominal waits of 1, 2 and 4 seconds
    between four attempts.

    jitter is the fraction subtracted from a computed delay d, giving
    a wait uniform in [d * (1 - jitter), d]. jitter=0.0 makes the
    schedule deterministic, which is the unit-test story. Full jitter
    (uniform in [0, d]) is rejected: a near-zero wait against a
    per-minute window that has not drained burns an attempt for
    nothing.

    sleep is injectable so tests record delays instead of serving
    them, and so the eval runner can substitute its own pacing if it
    ever needs to.
    """

    max_attempts: int = 4
    base_delay: float = 1.0
    max_delay: float = 15.0
    backoff_factor: float = 2.0
    jitter: float = 0.25
    classify: Callable[[Exception], bool] = is_retryable
    sleep: Callable[[float], None] = time.sleep

    def __post_init__(self) -> None:
        if self.max_attempts < 1:
            raise ValueError("max_attempts must be >= 1")
        if self.base_delay < 0 or self.max_delay < 0:
            raise ValueError("delays must be >= 0")
        if not 0.0 <= self.jitter <= 1.0:
            raise ValueError("jitter must be in [0, 1]")
        if self.backoff_factor < 1.0:
            raise ValueError("backoff_factor must be >= 1.0")


def compute_delay(
    attempt: int,
    policy: RetryPolicy,
    rng: Callable[[], float] = random.random,
) -> float:
    """Backoff in seconds after `attempt` failures (1-based: the wait
    following the first failure is attempt 1).

    min(max_delay, base_delay * backoff_factor ** (attempt - 1)),
    minus up to `jitter` of itself. Pure given rng; with jitter=0.0
    the rng result is multiplied by zero and the schedule is exact.
    """
    if attempt < 1:
        raise ValueError("attempt is 1-based")
    capped = min(
        policy.max_delay,
        policy.base_delay * policy.backoff_factor ** (attempt - 1),
    )
    return capped * (1.0 - policy.jitter * rng())

# count_tokens feeds the Conversation budget guard, which discards any
# failure and proceeds without summarisation. Retrying it would block
# the hot path for seconds to produce a result the caller throws away.
# This is a property of the call, not of the deployment, so it is not
# a configurable policy field: there is no entry point where retrying
# count_tokens is correct.
NO_RETRY = RetryPolicy(max_attempts=1)