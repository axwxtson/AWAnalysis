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

import hashlib

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


def prompt_digest(prompt: str) -> str:
    """sha256 of a rendered prompt string.

    Takes the string, never a version name. A name would be looked up in
    PROMPT_VERSIONS and re-derive whatever the label already claims, so it
    could not disagree with itself. Hashing what was actually passed is
    what makes a mislabelled artefact detectable.

    Block 7: 8026830 changed what v2.5.0 renders to between two runs both
    labelled v2.5.0, and nothing could catch it because the artefact
    recorded only the name.
    """
    return hashlib.sha256(prompt.encode()).hexdigest()


# The version of the system prompt currently in use.Change this to roll
# back or forward. The agent loop reads SYSTEM_PROMPT, which dispatches
# on this constant.
ACTIVE_PROMPT_VERSION = "v2.6.0"