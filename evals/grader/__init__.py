"""Two-layer grader for the AW Analysis eval harness.

Layer 1 (deterministic): assertions against the Stage 5 trace fields.
Layer 2 (LLM-as-judge): faithfulness and relevance scoring of the final
text against the tool results captured in the trace.

Module 6 lesson: report both layers, treat disagreement as signal,
calibrate the judge before trusting its scores.
"""

from __future__ import annotations