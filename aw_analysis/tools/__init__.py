"""Public surface of the tools package.

Stage 6 introduced `default_registry()` so the CLI and the eval harness
construct the same ToolRegistry from one place. Before Stage 6, the CLI
built the registry inline; the eval runner now needs the same registry,
and a copy-pasted second version would drift.
"""

from __future__ import annotations

from aw_analysis.tools.asset_profile import AssetProfileTool
from aw_analysis.tools.base import Tool, ToolRegistry, ToolResult
from aw_analysis.tools.crypto_price import CryptoPriceTool
from aw_analysis.tools.equity_price import EquityPriceTool
from aw_analysis.tools.market_news import MarketNewsTool


def default_registry() -> ToolRegistry:
    """Construct the standard three-tool registry used by AW Analysis.

    Mirrors what cli/main.py was doing inline pre-Stage 6. If a new tool
    is added in a future stage, this is the one place it gets wired in.
    """
    registry = ToolRegistry()
    registry.register(CryptoPriceTool())
    registry.register(EquityPriceTool())
    registry.register(AssetProfileTool())
    registry.register(MarketNewsTool())
    return registry


__all__ = [
    "Tool",
    "ToolRegistry",
    "ToolResult",
    "CryptoPriceTool",
    "EquityPriceTool",
    "AssetProfileTool",
    "MarketNewsTool",
    "default_registry",
]