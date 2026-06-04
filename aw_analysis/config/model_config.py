"""Per-task ModelConfig registry.

Stage 5 established this seam: every model call routes through
get_model_config(task_type). Stage 7 extends it with one new task type
(INTENT_CLASSIFICATION) and one Haiku-backed config. Call sites stay
unchanged.

The router in agent/orchestration.py picks WHICH config to use per
sub-query intent for the TOOL_SELECTION task type. That's the small
new bit Stage 7 adds — task-type routing was already here; query-class
routing is implemented at the orchestration layer rather than in this
registry, so the registry stays a one-key lookup.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from aw_analysis.config.model_pricing import HAIKU_MODEL, SONNET_MODEL
from aw_analysis.config.settings import SETTINGS


class TaskType(str, Enum):
    """Categories of model call the agent makes."""

    INTENT_CLASSIFICATION = "intent_classification"
    SYMBOL_DISAMBIGUATION = "symbol_disambiguation"
    TOOL_SELECTION = "tool_selection"
    FINAL_SYNTHESIS = "final_synthesis"
    REFUSAL = "refusal"
    CONTEXT_SUMMARISATION = "context_summarisation"
    JUDGE = "judge"


@dataclass(frozen=True)
class ModelConfig:
    """Bundle of model, temperature, and budget for one task type.

    rationale travels with the config so traces show WHY a setting was
    chosen, not just what.
    """

    model: str
    temperature: float
    max_tokens: int
    rationale: str


# The Stage-7 default model assignment. Sonnet-backed entries are the
# Stage-5 defaults; the new INTENT_CLASSIFICATION entry is Haiku.
#
# The TOOL_SELECTION default stays on Sonnet — the orchestration layer
# overrides per sub-query intent (price-only → Haiku) by looking up
# task-type-specific configs through this same registry; see
# orchestration.ROUTING_OVERRIDES.
MODEL_CONFIG_REGISTRY: dict[TaskType, ModelConfig] = {
    TaskType.INTENT_CLASSIFICATION: ModelConfig(
        model=HAIKU_MODEL,
        temperature=0.0,
        max_tokens=512,
        rationale=(
            "Structured JSON classification; small intent space; "
            "Haiku at temp 0 is sufficient and ~3x cheaper than Sonnet"
        ),
    ),
    TaskType.SYMBOL_DISAMBIGUATION: ModelConfig(
        model=HAIKU_MODEL,
        temperature=0.0,
        max_tokens=256,
        rationale=(
            "Single-symbol class lookup for the long tail; tiny JSON "
            "output; fires only when a symbol is absent from every "
            "curated keyspace, so cost is rare and bounded"
        ),
    ),
    TaskType.TOOL_SELECTION: ModelConfig(
        model=SETTINGS.default_model,
        temperature=0.2,
        max_tokens=1024,
        rationale="Module 5 Ex 5.2: predictable structure with theoretical headroom",
    ),
    TaskType.FINAL_SYNTHESIS: ModelConfig(
        model=SETTINGS.default_model,
        temperature=0.7,
        max_tokens=2048,
        rationale="Natural prose; 2.5x peak observed output on hardest existing query",
    ),
    TaskType.REFUSAL: ModelConfig(
        model=SETTINGS.default_model,
        temperature=0.0,
        max_tokens=512,
        rationale="Refusal wording is contract-shaped, not creative",
    ),
    TaskType.CONTEXT_SUMMARISATION: ModelConfig(
        model=SETTINGS.default_model,
        temperature=0.0,
        max_tokens=1024,
        rationale="Greedy condensation; deterministic structure",
    ),
    TaskType.JUDGE: ModelConfig(
        model=SETTINGS.default_model,
        temperature=0.0,
        max_tokens=1024,
        rationale="Stage 6 calibrated judge; non-determinism flagged as eval-side concern",
    ),
}


def get_model_config(task_type: TaskType) -> ModelConfig:
    """Look up the ModelConfig for a given task type.

    This is the seam: orchestration.py may call this with a derived
    task type (e.g. TOOL_SELECTION) and then apply a query-class
    override on top of it. Call sites inside Conversation continue to
    use this directly with no awareness of routing.
    """
    return MODEL_CONFIG_REGISTRY[task_type]