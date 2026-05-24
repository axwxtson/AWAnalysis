"""Command-line entry point.

Usage:
    aw "What's the current price of BTC?"
    aw                              # interactive mode (REPL with memory)
"""

from __future__ import annotations

import sys

from rich.console import Console
from rich.markdown import Markdown

from aw_analysis.agent import Conversation, TurnBudgetExceeded
from aw_analysis.agent.trace import TurnTrace
from aw_analysis.client import AnthropicClient
from aw_analysis.tools import ToolRegistry, default_registry
from aw_analysis.agent.orchestration import OrchestratedConversation


from aw_analysis.prompts.system import SYSTEM_PROMPT

console = Console()

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
        return f"{prefix}{tool_summary} | {token_summary} | {cost_summary} | {cfg_summary}"

    # Legacy TurnTrace path (preserves existing behaviour for tests)
    tool_summary = _format_tools(trace.tool_calls)
    token_summary = (
        f"tokens: in={trace.total_input_tokens} out={trace.total_output_tokens}"
    )
    cfg_summary = "cfg=" + "→".join(i.task_type for i in trace.iterations)
    if trace.context_summarised:
        cfg_summary += " *"
    return f"{tool_summary} | {token_summary} | {cfg_summary}"


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


def main() -> None:
    client = AnthropicClient()
    tools = default_registry()
    inner_conversation = Conversation(
        client=client,
        tools=default_registry(),
        system_prompt=SYSTEM_PROMPT,
    )
    conversation = OrchestratedConversation(
        client=client,
        conversation=inner_conversation,
    )
    # Single-shot mode
    if len(sys.argv) > 1:
        _handle(" ".join(sys.argv[1:]), conversation)
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