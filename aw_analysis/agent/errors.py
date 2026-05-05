"""Agent-loop exception types.

We define our own exceptions for two reasons:

1. To distinguish *recoverable* failures (a tool call timed out, retry it)
   from *terminal* ones (the message budget is exhausted, give up).
2. To give Stage 6 evals and Stage 8 observability something to assert
   against. "The agent raised TurnBudgetExceeded" is a useful signal;
   "the agent raised RuntimeError" is not.
"""

from __future__ import annotations


class AgentError(Exception):
    """Base class for all agent-loop errors."""


class TurnBudgetExceeded(AgentError):
    """The agent exceeded its maximum number of turns for a single send.

    This means the model kept requesting tools without producing a final
    answer. Either the task is too complex for the budget, or the model
    is stuck in a loop. Either way the loop terminates and the partial
    state is returned for inspection.
    """


class ToolDispatchError(AgentError):
    """A tool failed in a way the loop should surface to the model.

    Note: this is *raised* by tool dispatch when something goes wrong
    that we don't want to silently absorb. Most tool failures are
    handled gracefully (returned as ToolResult with success=False).
    This exception is for cases where dispatch itself can't continue —
    e.g. an unknown tool name when we expected validation upstream.
    """