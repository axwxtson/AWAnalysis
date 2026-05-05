"""Tool base class and registry.

A `Tool` knows three things:
1. Its Anthropic-facing schema (name, description, input schema).
2. How to execute given parsed input.
3. How to format its result for the model to read.

The registry maps tool names to instances and dispatches calls during
the agent loop, returning structured ToolResult objects rather than
bare strings so the loop can distinguish success from failure.
"""

from __future__ import annotations

import time
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any

from anthropic.types import ToolParam


@dataclass
class ToolResult:
    """Structured result from a tool dispatch."""

    name: str
    content: str  # what the model sees as tool_result content
    success: bool
    duration_ms: float
    error: str | None = None


class Tool(ABC):
    """Base class for all agent tools."""

    name: str
    description: str
    input_schema: dict[str, Any]

    def to_anthropic_param(self) -> ToolParam:
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": self.input_schema,
        }

    @abstractmethod
    def execute(self, **kwargs: Any) -> str:
        """Execute the tool. Return a string for the model to read.

        Raise on failure. The registry catches exceptions and converts
        them to ToolResult(success=False).
        """


class ToolRegistry:
    """Holds tools and dispatches calls by name."""

    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        if tool.name in self._tools:
            raise ValueError(f"Tool '{tool.name}' already registered")
        self._tools[tool.name] = tool

    def dispatch(self, name: str, tool_input: dict[str, Any]) -> ToolResult:
        """Look up a tool by name and execute it. Always returns a ToolResult."""
        start = time.perf_counter()
        tool = self._tools.get(name)
        if tool is None:
            duration_ms = (time.perf_counter() - start) * 1000
            return ToolResult(
                name=name,
                content=f"Error: unknown tool '{name}'",
                success=False,
                duration_ms=duration_ms,
                error="unknown_tool",
            )
        try:
            content = tool.execute(**tool_input)
            duration_ms = (time.perf_counter() - start) * 1000
            return ToolResult(
                name=name,
                content=content,
                success=True,
                duration_ms=duration_ms,
            )
        except Exception as exc:  # noqa: BLE001
            duration_ms = (time.perf_counter() - start) * 1000
            return ToolResult(
                name=name,
                content=f"Error executing {name}: {exc}",
                success=False,
                duration_ms=duration_ms,
                error=type(exc).__name__,
            )

    def to_anthropic_params(self) -> list[ToolParam]:
        return [t.to_anthropic_param() for t in self._tools.values()]

    def names(self) -> list[str]:
        return list(self._tools)