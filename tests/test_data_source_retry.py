"""Tests for data-source retry.

jitter=0.0 throughout, so compute_delay is exact and a recorded sleep is
an assertion rather than a range. sleep is injected as a list append, so
nothing here waits.
"""
from __future__ import annotations

import httpx
import pytest

from aw_analysis.client.retry import RetryPolicy
from aw_analysis.data_sources.retry import is_retryable_http, request_json


class _Boom(Exception):
    """Stand-in for CoinGeckoError or TwelveDataError."""


class _StubClient:
    """Returns or raises one queued outcome per get()."""

    def __init__(self, outcomes: list[object]) -> None:
        self._outcomes = list(outcomes)
        self.calls = 0

    def get(self, path: str, params: object = None) -> httpx.Response:
        self.calls += 1
        outcome = self._outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        assert isinstance(outcome, httpx.Response)
        return outcome


def _response(status: int, headers: dict[str, str] | None = None) -> httpx.Response:
    return httpx.Response(
        status,
        headers=headers or {},
        request=httpx.Request("GET", "https://example.test/x"),
    )


def _policy(slept: list[float]) -> RetryPolicy:
    return RetryPolicy(
        max_attempts=3,
        base_delay=1.0,
        max_delay=8.0,
        jitter=0.0,
        classify=is_retryable_http,
        sleep=slept.append,
    )


def _call(client: _StubClient, slept: list[float]) -> httpx.Response:
    return request_json(
        client, "/p", {}, error=_Boom, context="ctx", policy=_policy(slept)
    )


def test_rate_limit_is_retried_and_then_succeeds() -> None:
    slept: list[float] = []
    client = _StubClient([_response(429), _response(200)])

    resp = _call(client, slept)

    assert resp.status_code == 200
    assert client.calls == 2
    assert slept == [1.0]


def test_not_found_is_not_retried() -> None:
    """The profile path's deterministic failure. A 404 means the ticker
    does not exist, so a retry buys nothing and delays the answer."""
    slept: list[float] = []
    client = _StubClient([_response(404)])

    with pytest.raises(_Boom):
        _call(client, slept)

    assert client.calls == 1
    assert slept == []


def test_transport_error_is_retried() -> None:
    slept: list[float] = []
    client = _StubClient([httpx.ConnectError("down"), _response(200)])

    assert _call(client, slept).status_code == 200
    assert client.calls == 2


def test_server_advice_is_preferred_when_within_the_cap() -> None:
    slept: list[float] = []
    client = _StubClient([_response(429, {"retry-after": "5"}), _response(200)])

    _call(client, slept)

    assert slept == [5.0]


def test_server_advice_beyond_the_cap_falls_back_to_computed_backoff() -> None:
    """60 seconds against an 8 second cap. Obeying it would blow the
    latency bound the policy exists to give; the computed delay is used
    instead."""
    slept: list[float] = []
    client = _StubClient([_response(429, {"retry-after": "60"}), _response(200)])

    _call(client, slept)

    assert slept == [1.0]