"""Command-line entry point.

Usage:
    aw "What's the current price of BTC?"
    aw                              # interactive mode (REPL with memory)
"""

from __future__ import annotations

import argparse
import sys

from rich.console import Console
from rich.markdown import Markdown

# Importing aw_analysis.obs at startup registers the atexit flush hook,
# ensuring traces are flushed when the CLI exits.
import aw_analysis.obs  # noqa: F401 — import for side effects
from aw_analysis.agent import Conversation, TurnBudgetExceeded
from aw_analysis.agent.orchestration import OrchestratedConversation
from aw_analysis.client import AnthropicClient
from aw_analysis.config import get_settings
from aw_analysis.prompts import (
    ACTIVE_PROMPT_VERSION,
    PROMPT_VERSIONS,
    prompt_digest,
)
from aw_analysis.tools import default_registry

console = Console()

def _format_cache(iterations: list) -> str:
    """Cache creation and read totals across a turn.

    Both are printed even when zero. A read of zero beside a non-zero
    creation is a miss; both zero means caching is not firing at all.
    Those are different findings, and a line suppressed when empty would
    conflate them with each other and with the instrument being absent.
    """
    created = sum(i.cache_creation_input_tokens for i in iterations)
    read = sum(i.cache_read_input_tokens for i in iterations)
    return f"cache: created={created} read={read}"


def _format_tools(tool_calls: list) -> str:
    """Render the per-tool summary fragment of the tool-activity line.

    Format: "tools: ✓ get_crypto_price (193ms) ✗ web_search (412ms)"
    Empty calls render as "tools: (none)".
    """
    if not tool_calls:
        return "tools: (none)"
    parts = []
    for tc in tool_calls:
        mark = "✓" if getattr(tc, "success", True) else "✗"
        parts.append(f"{mark} {tc.name} ({tc.duration_ms}ms)")
    return "tools: " + " ".join(parts)

def _render_tool_activity(trace: object) -> str:
    """Render the tool-activity summary line for a turn.

    Accepts either an OrchestratedTurnTrace (new in Stage 7) or a
    TurnTrace (the older shape, still supported for tests and direct
    Conversation use). The function flattens whichever it receives.
    """
    from aw_analysis.agent.orchestration import OrchestratedTurnTrace

    if isinstance(trace, OrchestratedTurnTrace):
        plan = trace.decomposition_plan
        if plan is not None and not plan.is_single_intent:
            intents = " → ".join(sq.intent.value for sq in plan.sub_queries)
            prefix = f"plan: {intents} | "
        elif trace.decomposition_fallback_reason:
            prefix = "plan: fallback | "
        else:
            prefix = ""

        tool_summary = _format_tools(trace.tool_calls)
        token_summary = (
            f"tokens: in={trace.total_input_tokens} "
            f"out={trace.total_output_tokens}"
        )
        cost_summary = f"cost: ${trace.total_cost_usd:.4f}"
        cfg_summary = "cfg=" + "→".join(i.task_type for i in trace.iterations)
        if trace.safety_net_fired:
            cfg_summary += " [safety_net_fired]"
        cache_summary = _format_cache(trace.iterations)
        return (
            f"{prefix}{tool_summary} | {token_summary} | {cost_summary} "
            f"| {cache_summary} | {cfg_summary}"
        )

    # Legacy TurnTrace path (preserves existing behaviour for tests)
    tool_summary = _format_tools(trace.tool_calls)
    token_summary = (
        f"tokens: in={trace.total_input_tokens} out={trace.total_output_tokens}"
    )
    cfg_summary = "cfg=" + "→".join(i.task_type for i in trace.iterations)
    if trace.context_summarised:
        cfg_summary += " *"
    cache_summary = _format_cache(trace.iterations)
    return f"{tool_summary} | {token_summary} | {cache_summary} | {cfg_summary}"


def _handle(user_message: str, conversation: Conversation) -> None:
    console.print(f"\n[dim]> {user_message}[/dim]\n")
    try:
        with console.status("[cyan]thinking...[/cyan]"):
            trace = conversation.send(user_message)
    except TurnBudgetExceeded as exc:
        console.print(f"[yellow]Turn budget exceeded:[/yellow] {exc}")
        return

    line = _render_tool_activity(trace)
    if line:
        console.print(f"[dim]{line}[/dim]")
    console.print(Markdown(trace.final_text))
    console.print()


def _parse_args(argv: list[str]) -> argparse.Namespace:
    """Parse the command line.

    Separated from main() so the argument contract is testable without a
    key, a client, or a billed turn. The Block 7 probe compares three
    prompt versions on one fixed string, and that comparison is only
    valid if the string reaching the model is identical in every arm, so
    the flag has to leave the message rather than be joined into it.
    """
    parser = argparse.ArgumentParser(
        prog="aw",
        description="AW Analysis - cross-asset market intelligence agent.",
    )
    parser.add_argument(
        "--prompt-version",
        default=ACTIVE_PROMPT_VERSION,
        choices=sorted(PROMPT_VERSIONS),
        help="System prompt version to run. Defaults to the active one.",
    )
    parser.add_argument(
        "message",
        nargs="*",
        help="The question. Omit for interactive mode.",
    )
    return parser.parse_args(argv)


def main() -> None:
    # Parsing precedes the key check so --help and a mistyped version
    # both fail without needing credentials.
    args = _parse_args(sys.argv[1:])

    # Fail fast. Settings are lazy so the library imports without a key;
    # this is an application entry point, so a missing key is fatal here
    # and should say so before any work starts.
    get_settings()

    system_prompt = PROMPT_VERSIONS[args.prompt_version]
    client = AnthropicClient()
    inner_conversation = Conversation(
        client=client,
        tools=default_registry(),
        system_prompt=system_prompt,
    )
    conversation = OrchestratedConversation(
        client=client,
        conversation=inner_conversation,
        interface="cli",
    )
    # This path writes no run artefact, and orchestration.send stamps
    # every trace with ACTIVE_PROMPT_VERSION whichever prompt was passed.
    # The digest of what was actually built is the only per-turn record
    # of which arm ran, so it is printed rather than inferred.
    console.print(
        f"[dim]prompt: {args.prompt_version} "
        f"sha256={prompt_digest(system_prompt)}[/dim]"
    )

    # Single-shot mode
    if args.message:
        _handle(" ".join(args.message), conversation)
        return

    # Interactive REPL — context threads across turns
    console.print(
        "[bold cyan]AW Analysis[/bold cyan] — type 'exit' to quit, "
        "'reset' to clear history\n"
    )
    while True:
        try:
            user_message = console.input("[bold]you[/bold] ❯ ").strip()
        except (EOFError, KeyboardInterrupt):
            console.print()
            return
        if user_message.lower() in {"exit", "quit"}:
            return
        if user_message.lower() == "reset":
            conversation.reset()
            console.print("[dim]conversation reset[/dim]\n")
            continue
        if not user_message:
            continue
        _handle(user_message, conversation)


if __name__ == "__main__":
    main()