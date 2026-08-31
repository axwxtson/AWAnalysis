"""Retry reaches the data sources, not only the helper.

tests/test_data_source_retry.py exercises request_json directly. These
go through the real CoinGeckoClient and TwelveDataClient with only the
httpx client replaced, so they fail if a call site was wired wrongly or
missed. Both clients were wired on the strength of greps until this
file existed, and one of those greps did miss a site.

The policy is injected rather than patched onto the module, so nothing
here sleeps: sleep is a list append and jitter is zero. TwelveDataClient
takes an explicit api_key for the same reason, which keeps get_settings
and its lru_cache out of the test entirely.
"""
from __future__ import annotations

import httpx

from aw_analysis.client.retry import RetryPolicy
from aw_analysis.data_sources.coingecko import CoinGeckoClient
from aw_analysis.data_sources.retry import is_retryable_http
from aw_analysis.data_sources.twelvedata import TwelveDataClient


class _StubHttp:
    """Returns one queued response per get()."""

    def __init__(self, responses: list[httpx.Response]) -> None:
        self._responses = list(responses)
        self.calls = 0

    def get(self, path: str, params: object = None) -> httpx.Response:
        self.calls += 1
        return self._responses.pop(0)


def _response(status: int, body: dict[str, object]) -> httpx.Response:
    return httpx.Response(
        status,
        json=body,
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


def test_coingecko_price_survives_a_rate_limit() -> None:
    slept: list[float] = []
    source = CoinGeckoClient(retry=_policy(slept))
    stub = _StubHttp(
        [
            _response(429, {}),
            _response(200, {"bitcoin": {"usd": 64000.0, "usd_24h_change": 1.5}}),
        ]
    )
    source._client = stub

    got = source.get_price("BTC")

    assert got["price"] == 64000.0
    assert stub.calls == 2
    assert slept == [1.0]


def test_twelve_data_quote_survives_a_rate_limit() -> None:
    slept: list[float] = []
    source = TwelveDataClient(api_key="test-key", retry=_policy(slept))
    stub = _StubHttp(
        [
            _response(429, {}),
            _response(200, {"name": "Apple Inc.", "close": "185.5"}),
        ]
    )
    source._client = stub

    got = source.get_quote("AAPL")

    assert got["price"] == 185.5
    assert stub.calls == 2
    assert slept == [1.0]