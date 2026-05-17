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

from aw_analysis.prompts.system import SYSTEM_PROMPT

console = Console()


def _render_tool_activity(trace: TurnTrace) -> str:
    """One-line summary under each response.

    Stage 5 additions:
      - Token totals (in/out across all iterations)
      - Config sequence (e.g. tool_selection→final_synthesis)
      - * suffix if context summarisation fired
    """
    if not trace.tool_calls and not trace.iterations:
        return ""

    parts: list[str] = []

    if trace.tool_calls:
        tool_bits = []
        for call in trace.tool_calls:
            tick = "✓" if call.success else "✗"
            tool_bits.append(f"{tick} {call.name} ({call.duration_ms:.0f}ms)")
        parts.append("tools: " + ", ".join(tool_bits))

    if trace.iterations:
        cfg_seq = "→".join(trace.model_configs_used)
        token_bit = (
            f"tokens: in={trace.total_input_tokens} "
            f"out={trace.total_output_tokens}"
        )
        cfg_bit = f"cfg={cfg_seq}"
        if trace.context_summarised:
            cfg_bit += "*"
        parts.append(token_bit)
        parts.append(cfg_bit)

    return " | ".join(parts)


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
    conversation = Conversation(client=client, tools=tools, system_prompt=SYSTEM_PROMPT)

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