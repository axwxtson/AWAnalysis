"""Atexit hook to flush the Langfuse client on process exit.

The Langfuse v3 SDK batches spans for efficiency.  Without an
explicit flush, the last batch can be lost when a short-lived
CLI process exits.  Registering this hook on package import
ensures every invocation flushes cleanly.

Critical: this hook MUST NOT construct the Langfuse client.  By
the time atexit runs, the interpreter has torn down its thread
pool and the OTEL resource detector inside Langfuse's constructor
will raise `RuntimeError: cannot schedule new futures after
interpreter shutdown`.  We therefore peek at the cached client
directly and skip the flush if it was never built during the
process lifetime.
"""
from __future__ import annotations

import atexit
import sys
import threading

import aw_analysis.obs.client as _client_module

_REGISTERED = False
_LOCK = threading.Lock()


def _flush() -> None:
    """Flush the client if and only if it was already constructed.

    We deliberately do NOT call get_langfuse_client() here — that
    would lazy-build during shutdown, which crashes on Python 3.14.
    """
    cached = _client_module._CLIENT
    if cached is None:
        return
    try:
        cached.flush()
    except Exception as exc:  # noqa: BLE001
        sys.stderr.write(f"WARN obs: flush failed at shutdown: {exc}\n")


def register_shutdown_hook() -> None:
    """Idempotent registration of the atexit flush hook."""
    global _REGISTERED
    if _REGISTERED:
        return
    with _LOCK:
        if _REGISTERED:
            return
        atexit.register(_flush)
        _REGISTERED = True