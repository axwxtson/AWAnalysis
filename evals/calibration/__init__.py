"""Judge calibration: bias-test the LLM judge before trusting its scores.

Module 6 Ex 6.2 lesson: the v1 rubric there had 0% position consistency
and a length bias opposite to literature norms. Both findings were
invisible until calibration ran. This package is the AW Analysis
analogue of that calibration.
"""

from __future__ import annotations