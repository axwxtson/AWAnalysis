"""Smoke test for the observability facade.

This test is intentionally narrow: it asserts that the emitter
can be imported, that `is_enabled()` correctly reflects the env
var state, and that emit calls are safe no-ops when disabled.

We do NOT make real Langfuse API calls here — that's covered by
the manual single-CLI-invocation test in the test plan.
"""
from __future__ import annotations

import os
from unittest import mock

import pytest

from aw_analysis.obs import emitter as obs
from aw_analysis.obs.client import is_enabled


def test_is_enabled_false_when_keys_missing() -> None:
    """With no env vars, observability reports disabled."""
    with mock.patch.dict(os.environ, {}, clear=True):
        # Need to reset the warned-once flag for the test.
        import aw_analysis.obs.client as c
        c._WARNED_NO_KEYS = False
        assert is_enabled() is False


def test_turn_context_is_safe_when_disabled() -> None:
    """The turn context manager must not raise when keys are absent."""
    with mock.patch.dict(os.environ, {}, clear=True):
        import aw_analysis.obs.client as c
        c._WARNED_NO_KEYS = True  # suppress the warning during the test
        with obs.turn(
            user_message="hello",
            interface="test",
            prompt_version="v0.0.0",
        ) as turn:
            assert turn.span is None
            # All these calls should be safe no-ops.
            obs.classifier(turn, plan_intents=[], plan_texts=[], usage=None)
            obs.finalise(
                turn,
                final_text="ok",
                total_cost_usd=0.0,
                total_duration_ms=0.0,
                safety_net_fired=False,
                decomposition_fallback_reason=None,
            )
            obs.score(turn, name="test", value=1.0)


def test_warning_printed_once(capsys: object) -> None:
    """The missing-keys warning must print exactly once per process."""
    import aw_analysis.obs.client as c
    c._WARNED_NO_KEYS = False
    with mock.patch.dict(os.environ, {}, clear=True):
        is_enabled()
        is_enabled()
        is_enabled()
    captured = capsys.readouterr()  # type: ignore[attr-defined]
    assert captured.err.count("LANGFUSE_PUBLIC_KEY") == 1

def test_sub_query_propagates_exceptions_from_the_body() -> None:
    """Regression: the except clause used to wrap the yield.

    An exception thrown into the generator at the yield point was caught
    and the generator yielded a second time. Two yields in one `with` is
    a protocol violation, and Python reports it as "generator didn't
    stop after throw()" — replacing the real exception. TurnBudgetExceeded
    never reached its callers, and the red-team DoS attack recorded a
    RuntimeError instead. turn() documents the same failure; sub_query
    was missed.
    """
    import contextlib

    class _FakeSpan:
        def update(self, **kwargs: object) -> None:
            pass

    class _FakeClient:
        @contextlib.contextmanager
        def start_as_current_observation(self, **kwargs: object):
            yield _FakeSpan()

    with mock.patch.object(obs, "get_langfuse_client", lambda: _FakeClient()):
        turn = obs.Turn(span=_FakeSpan(), conversation_id="c", prompt_version="v0.0.0")
        with (
            pytest.raises(ValueError, match="from the body"),
            obs.sub_query(turn, intent="PRICE", text="q", index=0),
        ):
            raise ValueError("raised from the body")
            with obs.sub_query(turn, intent="PRICE", text="q", index=0):
                raise ValueError("raised from the body")


def test_sub_query_degrades_when_span_creation_fails() -> None:
    """The graceful path the except clause exists for must still work:
    if opening the span raises, the caller gets a null handle rather
    than an error."""

    class _BrokenClient:
        def start_as_current_observation(self, **kwargs: object):
            raise RuntimeError("langfuse unavailable")

    with mock.patch.object(obs, "get_langfuse_client", lambda: _BrokenClient()):
        turn = obs.Turn(span=object(), conversation_id="c", prompt_version="v0.0.0")
        with obs.sub_query(turn, intent="PRICE", text="q", index=0) as sq:
            assert sq.span is None