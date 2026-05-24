"""Per-model pricing table and cost computation for IterationUsage.

Module 7 cost-modelling support. Kept minimal: input and output rates
per million tokens, no caching adjustment yet (caching becomes Stage 8
or later; the table is structured to extend cleanly when it does).

Rates as of November 2025 (Anthropic public pricing). Update when
model versions or pricing change.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ModelPricing:
    """Per-model pricing in US dollars per million tokens."""

    input_per_mtok: float
    output_per_mtok: float

    def cost_usd(self, input_tokens: int, output_tokens: int) -> float:
        """Compute cost for a single call given measured token counts."""
        return (
            input_tokens * self.input_per_mtok / 1_000_000.0
            + output_tokens * self.output_per_mtok / 1_000_000.0
        )


# Canonical model strings used elsewhere in the codebase.
SONNET_MODEL = "claude-sonnet-4-6"
HAIKU_MODEL = "claude-haiku-4-5-20251001"

# Pricing table. Keys must match the model strings used in ModelConfig.
PRICING: dict[str, ModelPricing] = {
    SONNET_MODEL: ModelPricing(input_per_mtok=3.00, output_per_mtok=15.00),
    HAIKU_MODEL: ModelPricing(input_per_mtok=1.00, output_per_mtok=5.00),
}


def cost_for(model: str, input_tokens: int, output_tokens: int) -> float:
    """Look up pricing and compute call cost.

    Falls back to Sonnet rates if the model is unknown — better to
    over-report cost than to silently report zero. Stage-7 invariant:
    every model used by AnthropicClient.create should have an entry in
    PRICING; the fallback exists for safety, not for routine use.
    """
    pricing = PRICING.get(model)
    if pricing is None:
        pricing = PRICING[SONNET_MODEL]
    return pricing.cost_usd(input_tokens, output_tokens)