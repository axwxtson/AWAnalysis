# aw_analysis/config/__init__.py
"""Configuration package.

Re-exports the runtime Settings (previously in aw_analysis/config.py)
and exposes ModelConfig / TaskType for per-task LLM configuration
introduced in Stage 5.
"""
from __future__ import annotations

from aw_analysis.config.settings import Settings, SETTINGS
from aw_analysis.config.model_config import (
    ModelConfig,
    TaskType,
    MODEL_CONFIG_REGISTRY,
    get_model_config,
)

__all__ = [
    "Settings",
    "SETTINGS",
    "ModelConfig",
    "TaskType",
    "MODEL_CONFIG_REGISTRY",
    "get_model_config",
]