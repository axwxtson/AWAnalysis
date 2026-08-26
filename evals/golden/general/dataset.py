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

from evals.grader.types import (
    Assertion,
    AssertionKind,
    EvalCase,
    QueryClass,
    Severity,
)


def _no_tool_concept(
    case_id: str,
    query: str,
    rationale: str,
    difficulty: str,
    not_refused_note: str,
) -> EvalCase:
    """Every case in this dataset has the same two assertions.

    NOT_REFUSED at P0 is the guard: over-refusal is the failure this
    dataset exists to catch, so it fails the case.

    TOOL_NOT_CALLED at P1 is a routing signal, not a guard. Retrieving a
    profile for a question naming no asset is wasteful, and worth seeing
    in the artefact, but a correct answer that took a needless detour has
    not failed the thing being measured.
    """
    return EvalCase(
        id=case_id,
        query=query,
        query_class=QueryClass.CONCEPT,
        assertions=[
            Assertion(
                kind=AssertionKind.NOT_REFUSED,
                target="true",
                description=not_refused_note,
            ),
            Assertion(
                kind=AssertionKind.TOOL_NOT_CALLED,
                target="lookup_asset_profile",
                severity=Severity.P1,
                description="No asset is named; retrieval has nothing to resolve",
            ),
        ],
        rationale=rationale,
        difficulty=difficulty,
    )


# ---------- comfortable: the clause's own worked examples ----------

_WORKED_EXAMPLES: list[EvalCase] = [
    _no_tool_concept(
        "concept_proof_of_stake",
        "What is proof of stake?",
        (
            "Anchor 4: a worked example named in the No tool clause "
            "itself. If this over-refuses, the clause has stopped "
            "admitting the case its own text cites."
        ),
        "easy",
        "A worked example from the No tool clause must be answered",
    ),
    _no_tool_concept(
        "concept_stock_split",
        "What is a stock split?",
        (
            "Anchor 5: the second worked example in the No tool clause. "
            "Paired with proof of stake so the two asset domains are "
            "both represented among the comfortable cases."
        ),
        "easy",
        "A worked example from the No tool clause must be answered",
    ),
]


# ---------- comfortable: term and mechanism ----------

_TERM_AND_MECHANISM: list[EvalCase] = [
    _no_tool_concept(
        "concept_market_cap",
        "What is market capitalisation?",
        (
            "Anchor 1, what a term means. Expected to survive any "
            "narrowing of the subject limb, because it reads as a "
            "general market concept without needing the word asset. "
            "Included as a control: if this one fails, the problem is "
            "wider than the limb being tested."
        ),
        "easy",
        "A definitional market term must be answered",
    ),
    _no_tool_concept(
        "concept_earnings_report",
        "What is an earnings report and what goes in one?",
        (
            "Anchor 2, how a mechanism works. Reads as a market "
            "mechanism rather than a category of asset, so it is not "
            "counted toward the two marginal cases the falsification "
            "condition requires."
        ),
        "medium",
        "A market mechanism question must be answered",
    ),
]


# ---------- marginal: where the word 'asset' was doing the admitting ----------

_MARGINAL: list[EvalCase] = [
    _no_tool_concept(
        "concept_asset_class",
        "What is an asset class?",
        (
            "Anchor 1 in the region the falsification condition names. "
            "The subject is a taxonomy of assets, so with the word "
            "struck, admission rests entirely on whether this reads as "
            "a market or trading concept. Expected to be at risk."
        ),
        "hard",
        "A question about a category of asset must still be answered",
    ),
    _no_tool_concept(
        "concept_coin_vs_token",
        "What's the difference between a coin and a token?",
        (
            "Anchor 3, how an instrument behaves, and the second case "
            "in the at-risk region. Instrument behaviour in the "
            "abstract means categories of instrument rather than any "
            "covered one, which is precisely where the word asset was "
            "carrying the admission. Expected to be at risk."
        ),
        "hard",
        "A question comparing instrument categories must still be answered",
    ),
]


GENERAL_DATASET: list[EvalCase] = [
    *_WORKED_EXAMPLES,
    *_TERM_AND_MECHANISM,
    *_MARGINAL,
]