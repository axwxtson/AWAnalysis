"""The AW Analysis equities golden dataset.

Empty until Stage 9 step 5. Equity cases land only after the registry,
get_equity_price, and (class, intent) routing exist, so the crypto
suite can be proven green at the v2.4.0 lock before any equity code.
"""
from __future__ import annotations

from evals.grader.types import EvalCase

EQUITY_DATASET: list[EvalCase] = []