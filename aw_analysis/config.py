"""Configuration loading from environment."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

# Load .env from the repo root if present
load_dotenv(Path(__file__).resolve().parents[2] / ".env")


@dataclass(frozen=True)
class Settings:
    """Application settings, loaded from environment."""

    anthropic_api_key: str
    default_model: str
    log_level: str

    @classmethod
    def from_env(cls) -> "Settings":
        api_key = os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            raise RuntimeError(
                "ANTHROPIC_API_KEY is not set. "
                "Copy .env.example to .env and fill it in."
            )
        return cls(
            anthropic_api_key=api_key,
            default_model=os.environ.get("AW_DEFAULT_MODEL", "claude-sonnet-4-5"),
            log_level=os.environ.get("AW_LOG_LEVEL", "INFO"),
        )


SETTINGS = Settings.from_env()