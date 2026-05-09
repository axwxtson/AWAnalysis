# aw_analysis/config/model_config.py
"""Per-task model configuration.

Stage 5's central abstraction. Different shapes of agent-loop
iteration want different sampling and budget settings; we encode
those choices once, here, and look them up by TaskType.

Numbers are not arbitrary — see module-5-complete-reference.md
Exercises 5.1 and 5.2 for the measurements that justify them.
British English throughout.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from aw_analysis.config.settings import SETTINGS


class TaskType(str, Enum):
    """Categories of agent-loop iteration.

    The Conversation chooses one of these per call to the model.
    The mapping rule is in conversation.py — keep this enum in
    sync with that mapping.
    """

    TOOL_SELECTION = "tool_selection"
    FINAL_SYNTHESIS = "final_synthesis"
    REFUSAL = "refusal"
    # Used only by the context-budget summarisation call. Internal,
    # but worth its own type so the budget summarisation shows up
    # clearly in traces.
    CONTEXT_SUMMARISATION = "context_summarisation"


@dataclass(frozen=True)
class ModelConfig:
    """A complete description of how a single model call should behave.

    Attributes:
        model: The Anthropic model id (e.g. "claude-sonnet-4-5").
        temperature: Sampling temperature in [0.0, 1.0].
        max_tokens: Hard cap on the response. Going over truncates.
        rationale: One-line note on why these values were chosen,
            preserved alongside the config so the trace can surface
            it. This is how the codebase carries Module 5 findings
            forward visibly.
    """

    model: str
    temperature: float
    max_tokens: int
    rationale: str

    def __post_init__(self) -> None:
        # Cheap invariants. Failing fast here beats a confusing
        # 400 from the API.
        if not 0.0 <= self.temperature <= 1.0:
            raise ValueError(
                f"temperature must be in [0.0, 1.0], got {self.temperature}"
            )
        if self.max_tokens <= 0:
            raise ValueError(
                f"max_tokens must be positive, got {self.max_tokens}"
            )


# Registry. Keep these defaults in one place; Module 7 will replace
# the lookup function with a router but the registry stays.
#
# The model field is read from SETTINGS.default_model so a single env
# var change still flips the whole agent — that capability has been
# in place since Stage 1 and we don't want to lose it.
MODEL_CONFIG_REGISTRY: dict[TaskType, ModelConfig] = {
    TaskType.TOOL_SELECTION: ModelConfig(
        model=SETTINGS.default_model,
        temperature=0.2,
        max_tokens=1024,
        rationale=(
            "Low temperature for predictable tool-use structure. "
            "Module 5 Ex 5.2: 0.0–0.3 are effectively deterministic "
            "on short outputs."
        ),
    ),
    TaskType.FINAL_SYNTHESIS: ModelConfig(
        model=SETTINGS.default_model,
        temperature=0.7,
        max_tokens=2048,
        rationale=(
            "Higher temperature for natural prose synthesising tool "
            "results. Module 5 Ex 5.2: real diversity kicks in "
            "between 0.4–0.7. max_tokens 2048 is ~2.5x observed peak."
        ),
    ),
    TaskType.REFUSAL: ModelConfig(
        model=SETTINGS.default_model,
        temperature=0.0,
        max_tokens=512,
        rationale=(
            "Greedy decoding for refusals. Refusal language is a "
            "contract; consistency is a safety property. Short cap "
            "because refusals are short by design."
        ),
    ),
    TaskType.CONTEXT_SUMMARISATION: ModelConfig(
        model=SETTINGS.default_model,
        temperature=0.0,
        max_tokens=1024,
        rationale=(
            "Greedy summarisation. We want stable, factual condensation "
            "of past turns, not creative paraphrase."
        ),
    ),
}


def get_model_config(task_type: TaskType) -> ModelConfig:
    """Return the registered ModelConfig for a TaskType.

    Single point of indirection so Module 7 (router) can swap this
    out without touching the rest of the agent.
    """
    return MODEL_CONFIG_REGISTRY[task_type]