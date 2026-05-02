"""Prompt versioning.

Why version prompts? Two reasons:

1. Stage 6 will run evals. To compare "did this prompt change make things
   better?" we need the old prompt available alongside the new one. Without
   versioning, every prompt change is destructive.

2. In production, we want the ability to roll a prompt back instantly if
   it regresses. Versions make that trivial: change one constant.

The convention is semver-ish: bump MAJOR for behaviour changes that aren't
backwards-compatible (e.g. output format change), MINOR for additive
improvements, PATCH for fixes that don't change observable behaviour.
"""

from __future__ import annotations

# The version of the system prompt currently in use. Change this to roll
# back or forward. The agent loop reads SYSTEM_PROMPT, which dispatches
# on this constant.
ACTIVE_PROMPT_VERSION = "v2.0.0"

# All known prompt versions. Each entry holds the full system prompt
# string for that version. Old versions are kept here so evals and
# rollbacks work.
PROMPT_VERSIONS: dict[str, str] = {}


def register(version: str):
    """Decorator to register a prompt-builder function under a version."""

    def decorator(fn):
        PROMPT_VERSIONS[version] = fn()
        return fn

    return decorator