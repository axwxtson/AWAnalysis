"""
Per-task model configuration for the agent loop.

Stage 5 introduced this module: every model call in the codebase routes
through MODEL_CONFIG_REGISTRY[task_type], with measured defaults backed
by Module 5 findings. Stage 6 adds TaskType.JUDGE for the eval harness.
The eval grader is a model call; it goes through the same seam every
other call goes through. No exceptions.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from aw_analysis.config import SETTINGS


class TaskType(str, Enum):
    """The shape of work an iteration of the agent loop is doing.

    Stage 7 will replace MODEL_CONFIG_REGISTRY's lookup with a router
    that picks model by query class as well; the enum stays.
    """

    TOOL_SELECTION = "tool_selection"
    FINAL_SYNTHESIS = "final_synthesis"
    REFUSAL = "refusal"
    CONTEXT_SUMMARISATION = "context_summarisation"
    JUDGE = "judge"  # Stage 6: LLM-as-judge in eval harness


@dataclass(frozen=True)
class ModelConfig:
    """Frozen per-task model configuration.

    The `rationale` field is preserved into IterationUsage records so a
    future reader sees both what was used and why.
    """

    model: str
    temperature: float
    max_tokens: int
    rationale: str


MODEL_CONFIG_REGISTRY: dict[TaskType, ModelConfig] = {
    TaskType.TOOL_SELECTION: ModelConfig(
        model=SETTINGS.default_model,
        temperature=0.2,
        max_tokens=1024,
        rationale=(
            "Tool selection wants predictable structure. Module 5 Ex 5.2 "
            "showed 0.0-0.3 produce identical output 10/10 runs; 0.2 has "
            "theoretical headroom while staying on the deterministic side."
        ),
    ),
    TaskType.FINAL_SYNTHESIS: ModelConfig(
        model=SETTINGS.default_model,
        temperature=0.7,
        max_tokens=2048,
        rationale=(
            "Synthesis wants natural prose. Real diversity kicks in 0.4-0.7. "
            "max_tokens=2048 is ~2.5x the observed peak on the hardest "
            "existing query (combined tools, Solana)."
        ),
    ),
    TaskType.REFUSAL: ModelConfig(
        model=SETTINGS.default_model,
        temperature=0.0,
        max_tokens=512,
        rationale=(
            "Refusal language is a contract, not a creative property. "
            "Greedy decoding makes the contract reproducible."
        ),
    ),
    TaskType.CONTEXT_SUMMARISATION: ModelConfig(
        model=SETTINGS.default_model,
        temperature=0.0,
        max_tokens=1024,
        rationale=(
            "Summarisation is condensation. No room for creativity; greedy."
        ),
    ),
    TaskType.JUDGE: ModelConfig(
        model=SETTINGS.default_model,
        temperature=0.0,
        max_tokens=600,
        rationale=(
            "LLM-as-judge grading is a deterministic-grading contract. "
            "Module 6 Ex 6.2 pattern: temperature 0, calibrated rubric, "
            "JSON output. Sonnet rather than Haiku because calibration "
            "(Stage 6) verifies self-preference bias is small at this scale; "
            "if calibration fails, swap to Haiku and recalibrate."
        ),
    ),
}


def get_model_config(task_type: TaskType) -> ModelConfig:
    """The seam Stage 7 will replace.

    Currently a static lookup; Stage 7 makes it a function of (task_type,
    query_class). Call sites stay unchanged.
    """
    return MODEL_CONFIG_REGISTRY[task_type]