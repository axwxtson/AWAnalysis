"""Configuration loading from environment."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

# Load .env from the repo root if present
load_dotenv(Path(__file__).resolve().parents[2] / ".env")

REPO_ROOT = Path(__file__).resolve().parents[2]

@dataclass(frozen=True)
class Settings:
    """Application settings, loaded from environment."""

    anthropic_api_key: str
    voyage_api_key: str | None
    default_model: str
    embedding_model: str
    chroma_path: Path
    log_level: str

    @classmethod
    def from_env(cls) -> "Settings":
        api_key = os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            raise RuntimeError(
                "ANTHROPIC_API_KEY is not set. "
                "Copy .env.example to .env and fill it in."
            )

        chroma_raw = os.environ.get("AW_CHROMA_PATH", "./data/chroma")
        chroma_path = Path(chroma_raw)
        if not chroma_path.is_absolute():
            chroma_path = REPO_ROOT / chroma_path

        return cls(
            anthropic_api_key=api_key,
            voyage_api_key=os.environ.get("VOYAGE_API_KEY"),
            default_model=os.environ.get("AW_DEFAULT_MODEL", "claude-sonnet-4-5"),
            embedding_model=os.environ.get("AW_EMBEDDING_MODEL", "voyage-3"),
            chroma_path=chroma_path,
            log_level=os.environ.get("AW_LOG_LEVEL", "INFO"),
        )


SETTINGS = Settings.from_env()