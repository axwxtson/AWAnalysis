"""Config package.

Re-exports the runtime SETTINGS plus the ModelConfig registry so call
sites elsewhere can import from aw_analysis.config without knowing the
internal module layout.
"""

from __future__ import annotations

from aw_analysis.config.model_config import (
    MODEL_CONFIG_REGISTRY,
    ModelConfig,
    TaskType,
    get_model_config,
)
from aw_analysis.config.model_pricing import (
    HAIKU_MODEL,
    PRICING,
    SONNET_MODEL,
    ModelPricing,
    cost_for,
)
from aw_analysis.config.settings import SETTINGS

__all__ = [
    "SETTINGS",
    "MODEL_CONFIG_REGISTRY",
    "ModelConfig",
    "TaskType",
    "get_model_config",
    "ModelPricing",
    "PRICING",
    "SONNET_MODEL",
    "HAIKU_MODEL",
    "cost_for",
]