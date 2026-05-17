"""Position bias and length bias tests for the LLM judge.

Position bias (the v1 rubric in Module 6 Ex 6.2 scored 0% consistency):
present a pair of (better_answer, worse_answer) twice, swapping order.
A well-behaved judge picks the same winner regardless of order.

Length bias: present pairs that differ in length but are equivalent in
faithfulness/relevance. The judge should score them similarly.
"""

from __future__ import annotations

from dataclasses import dataclass

from aw_analysis.client import AnthropicClient
from aw_analysis.config.model_config import TaskType, get_model_config
from evals.grader.judge import _parse_judge_json  # internal but stable for own use


@dataclass(frozen=True)
class PairwiseCase:
    """A pair of answers where one is clearly better than the other."""

    id: str
    query: str
    better: str
    worse: str
    rubric_dimension: str  # human-readable for the judge prompt


@dataclass(frozen=True)
class LengthCase:
    """A pair of answers, equivalent in quality, that differ in length."""

    id: str
    query: str
    short: str
    long: str
    dimension: str


POSITION_CASES: list[PairwiseCase] = [
    PairwiseCase(
        id="pos_01",
        query="What is the price of Bitcoin?",
        better="$43,250.",
        worse=(
            "Bitcoin's price changes constantly and is influenced by many factors "
            "including market sentiment and macro conditions. Right now it's somewhere around $43,000-ish."
        ),
        rubric_dimension="relevance and directness",
    ),
    PairwiseCase(
        id="pos_02",
        query="Tell me about Ethereum",
        better=(
            "Ethereum is a smart-contract platform launched in 2015 by Vitalik Buterin "
            "and others. It transitioned to proof-of-stake via the Merge in September 2022."
        ),
        worse=(
            "Ethereum is a cryptocurrency. It's the second biggest one. It does smart contracts."
        ),
        rubric_dimension="depth and accuracy",
    ),
    PairwiseCase(
        id="pos_03",
        query="Will Bitcoin go up tomorrow?",
        better=(
            "I can't predict short-term price movements. I can share Bitcoin's "
            "current price and recent performance if that helps."
        ),
        worse=(
            "Bitcoin will probably go up tomorrow based on the current technical setup."
        ),
        rubric_dimension="appropriateness of refusal for a prediction question",
    ),
]


LENGTH_CASES: list[LengthCase] = [
    LengthCase(
        id="len_01",
        query="What is the price of Bitcoin?",
        short="Bitcoin is currently trading at $43,250.",
        long=(
            "Looking at the latest market data, Bitcoin is currently trading at "
            "$43,250. This figure reflects the present spot price across major "
            "exchanges and is the value most market participants would reference "
            "when discussing the current price of BTC."
        ),
        dimension="faithfulness",
    ),
    LengthCase(
        id="len_02",
        query="What is Solana?",
        short="Solana is a high-throughput layer-1 blockchain.",
        long=(
            "Solana is a high-throughput layer-1 blockchain. It is known for its "
            "high transaction throughput and low fees, achieved through a "
            "combination of proof-of-stake consensus and proof-of-history "
            "ordering. It was launched in 2020."
        ),
        dimension="relevance",
    ),
]


def run_position_bias(client: AnthropicClient) -> dict:
    """For each PairwiseCase, run both orderings; consistency is the
    fraction where the same answer wins regardless of order.

    Module 6 Ex 6.2 hard finding: v1 rubric scored 0% consistency across
    3 cases. Anything below 75% is unusable for pairwise eval.
    """
    consistent = 0
    rows = []
    for case in POSITION_CASES:
        # ordering A: better is shown first
        winner_a = _ask_pairwise(
            client, case.query, case.better, case.worse, case.rubric_dimension
        )
        # ordering B: worse is shown first
        winner_b = _ask_pairwise(
            client, case.query, case.worse, case.better, case.rubric_dimension
        )
        # In ordering A the "better" answer is choice 1; in ordering B it
        # is choice 2. Consistent => A picks 1 AND B picks 2.
        is_consistent = winner_a == 1 and winner_b == 2
        if is_consistent:
            consistent += 1
        rows.append(
            {
                "id": case.id,
                "ordering_a_winner": winner_a,
                "ordering_b_winner": winner_b,
                "consistent": is_consistent,
            }
        )
    return {
        "consistency_rate": round(consistent / len(POSITION_CASES), 2),
        "rows": rows,
    }


def run_length_bias(client: AnthropicClient) -> dict:
    """For each LengthCase, score the short and long versions
    independently and compute the gap.

    Mean signed gap = mean(score_long - score_short). A positive gap
    means the judge prefers longer (literature norm); negative means
    shorter. We flag if abs(gap) > 0.5.
    """
    gaps: list[float] = []
    rows = []
    for case in LENGTH_CASES:
        short_score = _ask_single(client, case.query, case.short, case.dimension)
        long_score = _ask_single(client, case.query, case.long, case.dimension)
        gap = long_score - short_score
        gaps.append(gap)
        rows.append(
            {
                "id": case.id,
                "short_score": short_score,
                "long_score": long_score,
                "gap_long_minus_short": gap,
            }
        )
    mean_gap = sum(gaps) / len(gaps) if gaps else 0.0
    return {
        "mean_signed_gap": round(mean_gap, 2),
        "abs_gap": round(abs(mean_gap), 2),
        "rows": rows,
    }


# ---------- internal judge calls ----------

def _ask_pairwise(
    client: AnthropicClient, query: str, choice_1: str, choice_2: str, dimension: str
) -> int:
    """Ask the judge which of two answers is better. Returns 1 or 2."""
    config = get_model_config(TaskType.JUDGE)
    user_text = (
        f"Query: {query}\n\n"
        f"Answer 1:\n{choice_1}\n\n"
        f"Answer 2:\n{choice_2}\n\n"
        f"Which answer is better on '{dimension}'? "
        'Return only JSON: {"score": 1 or 2, "reasoning": "<one sentence>"}.\n'
        "No other text."
    )
    response = client.create(
        config=config,
        messages=[{"role": "user", "content": user_text}],
        system="You are an evaluator picking between two answers.",
    )
    text = ""
    for block in response.content:
        if getattr(block, "type", None) == "text":
            text = block.text
            break
    score, _ = _parse_judge_json(text)
    return 1 if score == 1 else 2


def _ask_single(
    client: AnthropicClient, query: str, answer: str, dimension: str
) -> int:
    """Score one answer on one dimension. Returns 1-5."""
    config = get_model_config(TaskType.JUDGE)
    user_text = (
        f"Query: {query}\n\n"
        f"Answer:\n{answer}\n\n"
        f"Score the answer on '{dimension}' on a 1-5 scale.\n"
        "Length is irrelevant; concise answers should not be penalised "
        "and verbose answers should not be rewarded.\n"
        'Return only JSON: {"score": <1-5>, "reasoning": "<one sentence>"}.'
    )
    response = client.create(
        config=config,
        messages=[{"role": "user", "content": user_text}],
        system="You are an evaluator scoring an answer on one dimension.",
    )
    text = ""
    for block in response.content:
        if getattr(block, "type", None) == "text":
            text = block.text
            break
    score, _ = _parse_judge_json(text)
    return score