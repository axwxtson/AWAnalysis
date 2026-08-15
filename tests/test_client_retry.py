"""Unit tests for the client's retry layer.

Offline by construction: no credentials, no network, no wall-clock.
The SDK client is constructed with a fake key (construction makes no
request), and RetryPolicy.sleep is injected so waits are recorded
rather than served.

Most behaviour is tested against _with_retry directly, since that is
the unit. Two tests deliberately go through the public create() and
count_tokens() instead: Stage 9 shipped a severed forced-tool path
that the eval suite could not see, because the mechanism was correct
and the caller did not route through it. A retry loop that works but
is not called would fail the same way.
"""
from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import anthropic
import httpx
import pytest

from aw_analysis.client import NO_RETRY, AnthropicClient, RetryPolicy
from aw_analysis.client.retry import compute_delay, is_retryable
from aw_analysis.config import ModelConfig, get_settings

_REQUEST = httpx.Request("POST", "https://api.anthropic.com/v1/messages")


@pytest.fixture(autouse=True)
def _fake_credentials(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Give Settings a key without touching .env, and never leak it.

    get_settings is lru_cached, so the cache is cleared on the way in
    and on the way out; otherwise a fake-key Settings survives into
    whichever test file runs next.
    """
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key-never-sent")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def _status_error(status: int, retry_after: float | None = None) -> anthropic.APIStatusError:
    """Build a real SDK exception, not a stand-in.

    Classification reads status_code and the retry-after header, so a
    fake would be testing the fake.
    """
    headers = {"retry-after": str(retry_after)} if retry_after is not None else {}
    response = httpx.Response(status, request=_REQUEST, headers=headers)
    return anthropic.APIStatusError("simulated", response=response, body=None)


def _recording_policy(**overrides: Any) -> tuple[RetryPolicy, list[float]]:
    """A jitter-free policy whose sleeps land in a list."""
    slept: list[float] = []
    policy = RetryPolicy(jitter=0.0, sleep=slept.append, **overrides)
    return policy, slept


class _Raiser:
    """Callable that yields a scripted sequence of outcomes.

    Counts its own calls, so tests assert how many API calls were
    made rather than inferring it from sleep count.
    """

    def __init__(self, *outcomes: Any) -> None:
        self._outcomes = list(outcomes)
        self.calls = 0

    def __call__(self) -> Any:
        self.calls += 1
        outcome = self._outcomes[min(self.calls - 1, len(self._outcomes) - 1)]
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


# --- the compounding regression -------------------------------------


def test_sdk_retry_is_disabled() -> None:
    """The SDK must not retry underneath us.

    Asserts the effective attribute rather than the constructor
    argument. A mock-and-inspect-call_args test would pass even if the
    SDK renamed the kwarg or construction moved, which is exactly the
    silent return this test exists to prevent.
    """
    client = AnthropicClient()
    assert client._sdk.max_retries == 0


def test_sdk_default_is_still_nonzero() -> None:
    """Canary on the assumption this whole layer rests on.

    If this fails, the pinned SDK changed its retry default and the
    reasoning in retry.py needs re-reading. It is not a bug in our
    code.
    """
    assert anthropic.Anthropic(api_key="test-key-never-sent").max_retries == 2


# --- the loop --------------------------------------------------------


def test_retries_transient_failures_then_succeeds() -> None:
    policy, slept = _recording_policy()
    call = _Raiser(_status_error(429), _status_error(429), "ok")

    assert AnthropicClient(policy=policy)._with_retry(call) == "ok"
    assert call.calls == 3
    assert slept == [1.0, 2.0]


def test_bad_request_is_not_retried() -> None:
    """A 400 is deterministic. Retrying pays three times to fail once."""
    policy, slept = _recording_policy()
    call = _Raiser(_status_error(400))

    with pytest.raises(anthropic.APIStatusError):
        AnthropicClient(policy=policy)._with_retry(call)
    assert call.calls == 1
    assert slept == []


def test_overloaded_529_is_retried() -> None:
    """529 has no entry in RETRYABLE_STATUS_CODES; it matches >= 500.

    The SDK maps it to an unexported OverloadedError that does not
    subclass InternalServerError, so a type-tuple classifier would
    miss it.
    """
    policy, slept = _recording_policy()
    call = _Raiser(_status_error(529), "ok")

    assert AnthropicClient(policy=policy)._with_retry(call) == "ok"
    assert call.calls == 2
    assert slept == [1.0]


def test_our_own_exceptions_are_not_retried() -> None:
    """A TypeError from argument construction is our bug, not the API's."""
    policy, slept = _recording_policy()
    call = _Raiser(TypeError("malformed kwargs"))

    with pytest.raises(TypeError):
        AnthropicClient(policy=policy)._with_retry(call)
    assert call.calls == 1
    assert slept == []


def test_gives_up_after_max_attempts() -> None:
    """max_attempts counts the first call: 4 attempts, 3 sleeps."""
    policy, slept = _recording_policy()
    call = _Raiser(_status_error(429))

    with pytest.raises(anthropic.APIStatusError):
        AnthropicClient(policy=policy)._with_retry(call)
    assert call.calls == 4
    assert slept == [1.0, 2.0, 4.0]


def test_no_retry_policy_makes_exactly_one_call() -> None:
    policy, slept = _recording_policy()
    call = _Raiser(_status_error(429))

    with pytest.raises(anthropic.APIStatusError):
        AnthropicClient(policy=policy)._with_retry(call, policy=NO_RETRY)
    assert call.calls == 1
    assert slept == []


# --- retry-after -----------------------------------------------------


def test_retry_after_raises_the_wait() -> None:
    """Server advice is a floor: 8s advised beats a 1s computed wait."""
    policy, slept = _recording_policy()
    call = _Raiser(_status_error(429, retry_after=8), "ok")

    assert AnthropicClient(policy=policy)._with_retry(call) == "ok"
    assert slept == [8.0]


def test_retry_after_is_capped_by_max_delay() -> None:
    """The policy cap is a ceiling even when advice exceeds it."""
    policy, slept = _recording_policy()
    call = _Raiser(_status_error(429, retry_after=30), "ok")

    assert AnthropicClient(policy=policy)._with_retry(call) == "ok"
    assert slept == [15.0]


def test_unreachable_retry_after_fails_immediately() -> None:
    """Advice of 60s against a 45s remaining budget is unreachable.

    Sleeping into it pays the full latency to surface the same error.
    """
    policy, slept = _recording_policy()
    call = _Raiser(_status_error(429, retry_after=60))

    with pytest.raises(anthropic.APIStatusError):
        AnthropicClient(policy=policy)._with_retry(call)
    assert call.calls == 1
    assert slept == []


def test_remaining_budget_shrinks_with_attempts() -> None:
    """Advice reachable at attempt 1 can be unreachable at attempt 3.

    20s advice fits the 45s budget at attempt 1 and the 30s budget at
    attempt 2, but not the 15s budget at attempt 3.
    """
    policy, slept = _recording_policy()
    call = _Raiser(_status_error(429, retry_after=20))

    with pytest.raises(anthropic.APIStatusError):
        AnthropicClient(policy=policy)._with_retry(call)
    assert call.calls == 3
    assert slept == [15.0, 15.0]


# --- the boundary: do the public methods actually route through it? --


class _FakeMessages:
    def __init__(self, *outcomes: Any) -> None:
        self._raiser = _Raiser(*outcomes)

    @property
    def calls(self) -> int:
        return self._raiser.calls

    def create(self, **_: Any) -> Any:
        return self._raiser()

    def count_tokens(self, **_: Any) -> Any:
        return self._raiser()


def test_create_routes_through_retry() -> None:
    """The Stage 9 shape: a correct mechanism that nobody calls."""
    policy, slept = _recording_policy()
    client = AnthropicClient(policy=policy)
    messages = _FakeMessages(_status_error(429), "ok")
    client._sdk.messages = messages  # type: ignore[misc]

    result = client.create(
        config=ModelConfig(
            model="claude-sonnet-4-5",
            temperature=0.0,
            max_tokens=16,
            rationale="test",
        ),
        system="s",
        messages=[{"role": "user", "content": "hi"}],
    )

    assert result == "ok"
    assert messages.calls == 2
    assert slept == [1.0]


def test_count_tokens_does_not_retry() -> None:
    """Routed through the same helper, but with NO_RETRY.

    The Conversation budget guard discards any failure here, so a
    retry would block the hot path to produce a discarded result.
    """
    policy, slept = _recording_policy()
    client = AnthropicClient(policy=policy)
    messages = _FakeMessages(_status_error(429))
    client._sdk.messages = messages  # type: ignore[misc]

    with pytest.raises(anthropic.APIStatusError):
        client.count_tokens(
            model="claude-sonnet-4-5",
            system="s",
            messages=[{"role": "user", "content": "hi"}],
        )

    assert messages.calls == 1
    assert slept == []


# --- the pure functions ----------------------------------------------


def test_compute_delay_doubles_and_caps() -> None:
    policy = RetryPolicy(jitter=0.0, base_delay=1.0, max_delay=15.0)
    assert [compute_delay(n, policy) for n in (1, 2, 3, 4, 5, 6)] == [
        1.0,
        2.0,
        4.0,
        8.0,
        15.0,
        15.0,
    ]


def test_constant_delay_regime() -> None:
    """factor=1.0 is the only way to express a flat schedule.

    The eval path wants fixed waits: a rate window drains at a fixed
    rate, so the second failure does not mean "wait longer".
    """
    policy = RetryPolicy(jitter=0.0, base_delay=30.0, backoff_factor=1.0, max_delay=60.0)
    assert [compute_delay(n, policy) for n in (1, 2, 3)] == [30.0, 30.0, 30.0]


def test_jitter_stays_within_the_lower_bound() -> None:
    """Fractional jitter never draws a premature wait.

    Full jitter would allow a near-zero delay against an undrained
    window, wasting an attempt.
    """
    policy = RetryPolicy(base_delay=4.0, max_delay=60.0)
    draws = [compute_delay(1, policy) for _ in range(200)]
    assert all(3.0 <= d <= 4.0 for d in draws)
    assert len(set(draws)) > 1


def test_classification_boundaries() -> None:
    assert is_retryable(_status_error(429)) is True
    assert is_retryable(_status_error(408)) is True
    assert is_retryable(_status_error(409)) is True
    assert is_retryable(_status_error(500)) is True
    assert is_retryable(_status_error(529)) is True
    assert is_retryable(_status_error(400)) is False
    assert is_retryable(_status_error(401)) is False
    assert is_retryable(_status_error(404)) is False
    assert is_retryable(anthropic.APIConnectionError(request=_REQUEST)) is True
    assert is_retryable(ValueError("ours")) is False


@pytest.mark.parametrize(
    "kwargs",
    [
        {"max_attempts": 0},
        {"jitter": 1.5},
        {"backoff_factor": 0.5},
        {"base_delay": -1.0},
    ],
)
def test_policy_rejects_invalid_settings(kwargs: dict[str, Any]) -> None:
    """Fail where the policy is written, not mid-run."""
    with pytest.raises(ValueError):
        RetryPolicy(**kwargs)