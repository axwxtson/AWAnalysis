"""The cache breakpoint, and the floor it silently depends on.

The floor test is the point of this file. An undersized prefix is not an
error, so the only thing that notices a prompt rewrite dropping below
the minimum is a test that fails on the character count.
"""
from __future__ import annotations

from aw_analysis.prompts.caching import (
    HAIKU_MIN_CACHEABLE_TOKENS,
    MIN_SYSTEM_PROMPT_CHARS,
    cacheable_system,
)
from aw_analysis.prompts.system import SYSTEM_PROMPT


def test_system_prompt_clears_the_haiku_cache_floor() -> None:
    """Measured at 10,606 characters and 2,609 tokens on 31 August 2026.
    If this fails, re-measure with count_tokens before touching the
    constant. The ratio is a property of the text, not a fixed number.
    """
    assert len(SYSTEM_PROMPT) >= MIN_SYSTEM_PROMPT_CHARS


def test_the_floor_constant_is_above_the_haiku_minimum() -> None:
    """Guards the guard. The character floor is only meaningful if it
    converts to more tokens than Haiku requires, so this pins the
    conversion rather than leaving it in a comment.
    """
    assert MIN_SYSTEM_PROMPT_CHARS / 4.065 > HAIKU_MIN_CACHEABLE_TOKENS


def test_the_block_carries_the_text_unchanged() -> None:
    blocks = cacheable_system("hello")

    assert len(blocks) == 1
    assert blocks[0]["text"] == "hello"
    assert blocks[0]["cache_control"] == {"type": "ephemeral"}