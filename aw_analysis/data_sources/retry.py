"""Retry for the HTTP data sources.

The schedule is not reimplemented. RetryPolicy, compute_delay and
retry_after_seconds come from aw_analysis.client.retry, which owns them
already. Only classification is new, because the exception types differ:
that module tests anthropic.APIStatusError, these calls raise httpx.

retry_after_seconds is reused rather than copied because it is
provider-agnostic in fact if not in name. It reaches for
exc.response.headers by getattr, which httpx.HTTPStatusError satisfies,
and returns None for a transport error carrying no response at all,
which falls back to computed backoff rather than failing.

Not ported: the fail-fast check in AnthropicClient._with_retry, which
abandons early when the server's advice exceeds the remaining sleep
budget. Its absence is a choice rather than an oversight. It is the
subtlest reasoning in that module, and this helper is better obviously
correct than marginally faster.
"""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import httpx

from aw_analysis.client.retry import (
    RetryPolicy,
    compute_delay,
    retry_after_seconds,
)

# 408 request timeout, 429 rate limit. 5xx needs no entry: the range
# test in is_retryable_http covers it.
RETRYABLE_STATUS_CODES = frozenset({408, 429})


def is_retryable_http(exc: Exception) -> bool:
    """Decide whether an httpx failure is worth another attempt.

    Retryable: transport errors, 408, 429 and >= 500.

    Everything else fails on the first attempt, and 404 is the case that
    matters. A 404 from CoinGecko's search endpoint means the ticker does
    not exist, so retrying sleeps to reach the same answer and delays a
    correct failure. Excluded by omission rather than by a special case.

    TransportError rather than its parent RequestError: RequestError also
    covers TooManyRedirects and DecodingError, and an identical second
    request fixes neither.
    """
    if isinstance(exc, httpx.TransportError):
        return True
    if isinstance(exc, httpx.HTTPStatusError):
        code = exc.response.status_code
        return code in RETRYABLE_STATUS_CODES or code >= 500
    return False


# Three attempts at an 8 second cap bounds worst-case sleeping at 16
# seconds, using the bound RetryPolicy documents. The Anthropic default
# of four attempts at 15 seconds would put roughly 45 seconds of sleep
# inside one tool call, inside an agent turn, inside an eval case.
DATA_SOURCE_RETRY = RetryPolicy(
    max_attempts=3,
    base_delay=1.0,
    max_delay=8.0,
    classify=is_retryable_http,
)


def request_json(
    client: httpx.Client,
    path: str,
    params: Mapping[str, Any],
    *,
    error: type[Exception],
    context: str,
    policy: RetryPolicy | None = None,
) -> httpx.Response:
    """GET `path`, retrying transient failures, wrapping on exhaustion.

    raise_for_status runs inside the loop so the classifier sees the
    httpx status while it is still intact. The domain error is built
    once, after attempts are exhausted, rather than at the point of
    failure. Wrapping first is exactly what makes the status code
    unavailable to anything that might want to decide on it.

    Server advice is preferred over computed backoff when it is within
    the policy cap. Advice beyond the cap is ignored rather than obeyed
    or failed on, which is the simplification named in the module
    docstring.
    """
    active = policy or DATA_SOURCE_RETRY
    last: Exception | None = None
    for attempt in range(1, active.max_attempts + 1):
        try:
            resp = client.get(path, params=dict(params))
            resp.raise_for_status()
        except httpx.HTTPError as exc:
            last = exc
            if attempt == active.max_attempts or not active.classify(exc):
                break
            wait = compute_delay(attempt, active)
            advised = retry_after_seconds(exc)
            if advised is not None and advised <= active.max_delay:
                wait = advised
            active.sleep(wait)
        else:
            return resp
    raise error(f"{context}: {last}") from last