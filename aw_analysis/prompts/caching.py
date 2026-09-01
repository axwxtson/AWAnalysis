"""Prompt caching: the breakpoint, and the size floor it depends on.

A cache_control breakpoint does nothing unless the prefix clears a
model-specific minimum. Below it the API accepts the request, returns no
error, and simply does not cache. That silence is why the floor is a
constant here with a test under it rather than a comment: a prompt
rewrite dropping below it would break caching with nothing to notice.

Measured 31 August 2026 with count_tokens against the identifiers in
aw_analysis/config/model_pricing.py. SYSTEM_PROMPT is 2,609 tokens on
both claude-sonnet-4-6 and claude-haiku-4-5-20251001, from 10,606
characters. That is 4.065 characters per token, and 27% clear of the
Haiku floor, which is the binding one because PRICE intent routes there.
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