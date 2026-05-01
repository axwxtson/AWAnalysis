"""Tool base class and registry.

A `Tool` knows three things:
1. Its Anthropic-facing schema (name, description, input schema).
2. How to execute given parsed input.
3. How to format its result for the model to read.

The registry maps tool names to instances, and dispatches calls during
the agent loop.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from anthropic.types import ToolParam


class Tool(ABC):
    """Base class for all agent tools."""

    name: str
    description: str
    input_schema: dict[str, Any]

    def to_anthropic_param(self) -> ToolParam:
        """Convert to the dict shape the Anthropic SDK expects."""
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": self.input_schema,
        }

    @abstractmethod
    def execute(self, **kwargs: Any) -> str:
        """Execute the tool. Return a string for the model to read.

        Returning a string (not a dict) keeps the contract simple:
        whatever you return goes straight into the tool_result content.
        Tools that produce structured data should JSON-encode it.
        """


class ToolRegistry:
    """Holds tools and dispatches calls by name."""

    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        if tool.name in self._tools:
            raise ValueError(f"Tool '{tool.name}' already registered")
        self._tools[tool.name] = tool

    def dispatch(self, name: str, tool_input: dict[str, Any]) -> str:
        """Look up a tool by name and execute it with the given input."""
        tool = self._tools.get(name)
        if tool is None:
            return f"Error: unknown tool '{name}'"
        try:
            return tool.execute(**tool_input)
        except Exception as exc:  # noqa: BLE001
            # We catch broadly here on purpose: a tool failure should not
            # crash the agent loop. The error becomes the tool result, and
            # the model can decide what to do (retry, ask the user, etc.).
            return f"Error executing {name}: {exc}"

    def to_anthropic_params(self) -> list[ToolParam]:
        return [t.to_anthropic_param() for t in self._tools.values()]