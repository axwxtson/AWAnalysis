"""Config package.

Re-exports the settings accessor plus the ModelConfig registry so call
sites elsewhere can import from aw_analysis.config without knowing the
internal module layout.

Settings are lazy: call get_settings() at use time rather than binding a
module-level value at import.
"""

from __future__ import annotations

from aw_analysis.config.model_config import (
    DEFAULT_MODEL,
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
from aw_analysis.config.settings import REPO_ROOT, Settings, get_settings

__all__ = [
    "DEFAULT_MODEL",
    "HAIKU_MODEL",
    "MODEL_CONFIG_REGISTRY",
    "PRICING",
    "REPO_ROOT",
    "SONNET_MODEL",
    "ModelConfig",
    "ModelPricing",
    "Settings",
    "TaskType",
    "cost_for",
    "get_model_config",
    "get_settings",
]
