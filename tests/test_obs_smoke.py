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