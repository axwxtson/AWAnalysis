"""Hand-curated golden datasets, partitioned by asset class.

Asset-class is an orthogonal partition of the dataset; QueryClass
remains the intent axis and is shared across classes. The runner is
invoked per asset-class and tags its output accordingly — cases do
not carry an asset_class field, so it cannot drift from the package
they live in.
"""
from __future__ import annotations

from evals.golden.crypto.dataset import CRYPTO_DATASET
from evals.golden.equities.dataset import EQUITY_DATASET
from evals.grader.types import EvalCase

ASSET_CLASSES: tuple[str, ...] = ("crypto", "equities")

DATASETS_BY_ASSET_CLASS: dict[str, list[EvalCase]] = {
    "crypto": CRYPTO_DATASET,
    "equities": EQUITY_DATASET,
}


def cases_for(asset_class: str) -> list[EvalCase]:
    """Return the golden cases for one asset class."""
    return DATASETS_BY_ASSET_CLASS[asset_class]