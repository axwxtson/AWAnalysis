"""Observability facade.

Public API for emitting traces to Langfuse. Every call site in the
agent and the evals goes through this module; the rest of the
package never imports Langfuse directly. The point of the
indirection is that if Langfuse is removed or replaced, the change
is local to `aw_analysis/obs/`.

Usage:

    from aw_analysis.obs import emitter

    with emitter.turn(user_message=msg, interface="cli") as turn:
        ...
        emitter.classifier(turn, plan=..., usage=...)
        with emitter.sub_query(turn, intent="price", text=...) as sq:
            emitter.iteration(sq, usage=..., text_in=..., text_out=...)
            emitter.tool_call(sq, tool_call=...)
        emitter.synthesis(turn, usage=...)
        emitter.finalise(turn, final_text=..., trace=orchestrated_trace)
"""
from __future__ import annotations

from aw_analysis.obs import emitter as emitter  # noqa: F401 — public re-export
from aw_analysis.obs.client import is_enabled, get_langfuse_client  # noqa: F401
from aw_analysis.obs.shutdown import register_shutdown_hook  # noqa: F401

# Register the atexit flush on package import.  Cheap, idempotent, and
# ensures CLI invocations always flush before the process exits.
register_shutdown_hook()