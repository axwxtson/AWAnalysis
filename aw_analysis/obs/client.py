"""Langfuse client singleton and readiness check.

Wraps `langfuse.get_client()` with two pieces of policy:
  - environment variables are read once at first call;
  - if keys are missing the facade prints a single warning to
    stderr and every subsequent call is a no-op.

The "one warning, never blocking" contract is what makes the
optional-but-noisy failure mode safe.  Silent no-op was rejected
because it produces the failure where the developer believes
traces are being emitted and they are not.
"""
from __future__ import annotations

import os
import sys
import threading
from typing import Any

# Langfuse is imported lazily inside `_init_client` so that
# import-time of this module is cheap and never depends on the
# Langfuse SDK being installed in non-observability environments.
_CLIENT: Any | None = None
_INIT_LOCK = threading.Lock()
_WARNED_NO_KEYS = False


def _has_required_env() -> bool:
    """Return True iff the minimal Langfuse env vars are set.

    `LANGFUSE_HOST` is optional (defaults to Langfuse Cloud), so
    only the two keys are required.
    """
    return bool(
        os.environ.get("LANGFUSE_PUBLIC_KEY")
        and os.environ.get("LANGFUSE_SECRET_KEY")
    )


def _warn_once_missing_keys() -> None:
    """Emit a single stderr warning when env vars are absent.

    Subsequent calls return without printing.  This is the only
    user-visible signal that observability is disabled.
    """
    global _WARNED_NO_KEYS
    if _WARNED_NO_KEYS:
        return
    _WARNED_NO_KEYS = True
    sys.stderr.write(
        "WARN obs: LANGFUSE_PUBLIC_KEY / LANGFUSE_SECRET_KEY not set — "
        "traces will not be emitted (set env vars to enable)\n"
    )


def is_enabled() -> bool:
    """Return True iff observability is configured and active.

    Call sites in the emitter use this as a fast path: if it
    returns False, the call returns immediately without
    constructing observation payloads.
    """
    if _has_required_env():
        return True
    _warn_once_missing_keys()
    return False


def get_langfuse_client() -> Any | None:
    """Return the process-level Langfuse client, or None if disabled.

    The client is constructed once on first call.  Guarded by a
    threading lock so concurrent first-callers don't race on
    construction; in practice the codebase is single-threaded but
    the cost of the lock is negligible.
    """
    global _CLIENT
    if not _has_required_env():
        _warn_once_missing_keys()
        return None
    if _CLIENT is not None:
        return _CLIENT
    with _INIT_LOCK:
        if _CLIENT is not None:
            return _CLIENT
        # Lazy import — the Langfuse SDK is only required when
        # observability is actually enabled.  Suppress the
        # pydantic.v1 deprecation warning Langfuse emits under
        # Python 3.14; it's cosmetic (the v1 namespace is API
        # response model declarations, not the emit path) and
        # tracked upstream at langfuse/langfuse#9618.  We do NOT
        # want this warning training us to ignore stderr — the
        # missing-keys warning is the one that matters.
        import warnings
        with warnings.catch_warnings():
            warnings.filterwarnings(
                "ignore",
                message=r"Core Pydantic V1 functionality isn't compatible.*",
                category=UserWarning,
            )
            from langfuse import get_client  # type: ignore[import-not-found]
        _CLIENT = get_client()
        return _CLIENT