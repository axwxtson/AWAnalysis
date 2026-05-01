"""Command-line entry point.

Usage:
    aw "What's the current price of BTC?"
    aw                              # interactive mode
"""

from __future__ import annotations

import sys

from rich.console import Console
from rich.markdown import Markdown

from aw_analysis.agent import run_agent
from aw_analysis.client import AnthropicClient
from aw_analysis.tools import CryptoPriceTool, ToolRegistry

console = Console()


def _build_registry() -> ToolRegistry:
    registry = ToolRegistry()
    registry.register(CryptoPriceTool())
    return registry


def _handle(user_message: str, client: AnthropicClient, tools: ToolRegistry) -> None:
    console.print(f"\n[dim]> {user_message}[/dim]\n")
    with console.status("[cyan]thinking...[/cyan]"):
        reply = run_agent(user_message, client, tools)
    console.print(Markdown(reply))
    console.print()


def main() -> None:
    client = AnthropicClient()
    tools = _build_registry()

    # If args are passed, run once and exit
    if len(sys.argv) > 1:
        _handle(" ".join(sys.argv[1:]), client, tools)
        return

    # Otherwise, interactive REPL
    console.print("[bold cyan]AW Analysis[/bold cyan] — type 'exit' to quit\n")
    while True:
        try:
            user_message = console.input("[bold]you[/bold] ❯ ").strip()
        except (EOFError, KeyboardInterrupt):
            console.print()
            return
        if user_message.lower() in {"exit", "quit"}:
            return
        if not user_message:
            continue
        _handle(user_message, client, tools)


if __name__ == "__main__":
    main()