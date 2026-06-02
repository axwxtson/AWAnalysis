"""Canonical attribute keys used on Langfuse observations.

Centralising key names prevents the silent drift where an emit
site writes `model_name` while a dashboard reads `model`.  All
keys live here as module-level constants; every emit site and
every dashboard query reference these names.

Naming convention: lowercase, dot-separated, scoped by concern.
Compatible with OpenTelemetry semantic conventions where
practical (`model.name`, `usage.tokens.input`, etc.)
"""
from __future__ import annotations

# ── Trace-level attributes (root span / trace) ──────────────────────
PROMPT_VERSION = "prompt.version"
QUERY_CLASS = "query.class"
INTERFACE = "interface"
CONVERSATION_ID = "conversation.id"
TOTAL_COST_USD = "cost.total.usd"
TOTAL_DURATION_MS = "duration.total.ms"
SAFETY_NET_FIRED = "safety_net.fired"
DECOMPOSITION_FALLBACK_REASON = "decomposition.fallback_reason"

# ── Sub-query attributes ────────────────────────────────────────────
SUB_QUERY_INTENT = "sub_query.intent"
SUB_QUERY_TEXT = "sub_query.text"
SUB_QUERY_INDEX = "sub_query.index"

# ── Iteration / generation attributes ───────────────────────────────
TASK_TYPE = "task.type"
MODEL_NAME = "model.name"
MODEL_TEMPERATURE = "model.temperature"
MODEL_MAX_TOKENS = "model.max_tokens"
STOP_REASON = "stop.reason"
TOKEN_INPUT = "usage.tokens.input"
TOKEN_OUTPUT = "usage.tokens.output"
COST_USD = "cost.usd"
DURATION_MS = "duration.ms"
RATIONALE = "model.rationale"

# ── Tool call attributes ────────────────────────────────────────────
TOOL_NAME = "tool.name"
TOOL_SUCCESS = "tool.success"
TOOL_ERROR_TAG = "tool.error_tag"
TOOL_DURATION_MS = "tool.duration.ms"

# ── Eval attributes ─────────────────────────────────────────────────
EVAL_CASE_ID = "eval.case_id"
EVAL_RUN_ID = "eval.run_id"
EVAL_CASE_PASSED = "eval.case.passed"

# ── Tags (Langfuse tags, used for top-level filtering) ──────────────
def tag_prompt_version(version: str) -> str:
    return f"prompt:{version}"


def tag_interface(interface: str) -> str:
    return f"interface:{interface}"