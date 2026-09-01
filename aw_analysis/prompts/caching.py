"""Prompt caching: the breakpoint, and the size floor it depends on.

A cache_control breakpoint does nothing unless the prefix clears a
model-specific minimum. Below it the API accepts the request, returns no
error, and simply does not cache. That silence is why the floor is a
constant here with a test under it rather than a comment: a prompt
rewrite dropping below it would break caching with nothing to notice.

Measured 31 August 2026. SYSTEM_PROMPT is 2,609 tokens on both
claude-sonnet-4-6 and claude-haiku-4-5-20251001, from 10,606 characters,
so 4.065 characters per token.

The system prompt is not most of what gets cached. A live turn reported a
10,208 token prefix with the full registry and 3,394 with web_search
removed, so 6,814 tokens, two thirds of it, are that server tool's
injected instructions. count_tokens cannot see any of this. It rejects
server tools outright, so it undercounts the real prefix by more than it
counts.

That makes MIN_SYSTEM_PROMPT_CHARS conservative rather than binding. The
live prefix clears the Haiku floor roughly fivefold, so the system prompt
could halve and caching would carry on. The floor is kept for the case
where the tool registry shrinks as well, which is the only way the prefix
could actually approach the minimum.
"""
from __future__ import annotations

from typing import Any

SONNET_MIN_CACHEABLE_TOKENS = 1024
HAIKU_MIN_CACHEABLE_TOKENS = 2048

# Character floor for the guard test. 2,048 tokens at the measured 4.065
# ratio is about 8,325 characters; 9,000 leaves headroom for the ratio
# itself moving, since it is a property of the text rather than a
# constant. A proxy, deliberately: token counts cannot be computed
# offline, so the test trips early rather than exactly.
MIN_SYSTEM_PROMPT_CHARS = 9000


def cacheable_system(prompt: str) -> list[dict[str, Any]]:
    """The system prompt as one cached block.

    AnthropicClient.create already declares system as str or a block
    list, so this needs no client change. The rendered text is
    unchanged, so prompt_digest of the same string is unchanged and no
    re-baseline is licensed by adding it.
    """
    return [
        {
            "type": "text",
            "text": prompt,
            "cache_control": {"type": "ephemeral"},
        }
    ]