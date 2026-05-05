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
from aw_analysis.client import AnthropicClient
from aw_analysis.tools import CryptoPriceTool, ToolRegistry

console = Console()


def _build_registry() -> ToolRegistry:
    registry = ToolRegistry()
    registry.register(CryptoPriceTool())
    return registry


def _print_trace_summary(trace) -> None:
    """Print a one-line summary of a turn's tool activity."""
    if not trace.tool_calls:
        return
    parts = []
    for tc in trace.tool_calls:
        marker = "✓" if tc.success else "✗"
        parts.append(f"{marker} {tc.name} ({tc.duration_ms:.0f}ms)")
    console.print(f"[dim]tools: {' · '.join(parts)}[/dim]")


def _handle(user_message: str, conversation: Conversation) -> None:
    console.print(f"\n[dim]> {user_message}[/dim]\n")
    try:
        with console.status("[cyan]thinking...[/cyan]"):
            trace = conversation.send(user_message)
    except TurnBudgetExceeded as exc:
        console.print(f"[yellow]Turn budget exceeded:[/yellow] {exc}")
        return

    _print_trace_summary(trace)
    console.print(Markdown(trace.final_text))
    console.print()


def main() -> None:
    client = AnthropicClient()
    tools = _build_registry()
    conversation = Conversation(client=client, tools=tools)

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