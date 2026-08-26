"""General financial-literacy cases: questions naming no asset.

Why this dataset exists
-----------------------
The system prompt's `No tool` clause governs when *not* to retrieve, and
nothing in the golden suite exercises it. Of the 39 cases in crypto and
equities, 31 expect a tool and 8 are refusals that should refuse.
TOOL_NOT_CALLED appears once, on `refusal_btc_prediction`, which is a
refusal rather than a concept question answered without a tool.

These cases name no asset, which is why they are a separate dataset
rather than crypto cases. Filing them under crypto would make that
artefact report 29 cases and put the burden of never merging them with
the locked 23 on memory rather than on structure.

Derivation rule
---------------
Cases are derived from what the prompt claims to admit, as committed at
v2.6.0, not from any change under consideration. Five anchors, all
present in the prompt before Block 7 began:

  1. the scope test's subject limb: what a term means
  2. the same limb: how a mechanism works
  3. the same limb: how an instrument behaves
  4. the `No tool` clause's worked example: proof of stake
  5. the same clause's worked example: a stock split

Roughly two per named category, chosen to span the clause rather than to
pass it. Any case added later states which anchor it derives from.

Falsification condition
-----------------------
A guard that cannot fail is not a guard. If every case passes on a
candidate prompt that narrows the subject limb, this set is suspect, not
confirmed.

At least two cases must sit in the region where the word "asset" was
doing the admitting and "market or trading concept" is a stretch. If two
such cases cannot be written, the risk this dataset guards against does
not exist, and that should be recorded here rather than padded around
with six comfortable cases.

Ordering claim
--------------
This derivation rule is committed before any case in this file and before
any candidate prompt exists. The claim is therefore that cases were
selected under a published rule, not that the selection was blind: the
same person knew which limb was about to change.

Grading
-------
CONCEPT cases are excluded from the faithfulness gate, because an answer
citing no tool results has no context for that rubric to grade against.
Relevance gates them instead, which is the only signal that separates a
real answer from a hedge that never trips the refusal classifier. This is
the first place relevance decides anything in this suite, so it is
uncalibrated for this use.
"""

from __future__ import annotations

from evals.grader.types import EvalCase

GENERAL_DATASET: list[EvalCase] = []