"""AW Analysis automated eval harness.

Stage 6: end-to-end evaluation against a hand-curated golden dataset.
Two-layer grading (deterministic + LLM-as-judge) with calibration as a
prerequisite for trusting judge scores.

The harness is a *consumer* of aw_analysis. Production code does not
import from this package; this package freely imports from aw_analysis.
That dependency direction is enforced by file layout.
"""

from __future__ import annotations

__version__ = "0.1.0"