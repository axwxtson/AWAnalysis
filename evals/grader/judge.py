"""LLM-as-judge grader layer.

Module 6 reference: judge calibration is a prerequisite for trust.
Stage 6 ships v1 of the rubric and a calibration pass. The runner will
refuse to gate on judge scores until calibration passes its thresholds.

Three rubrics:
  - Faithfulness: does the answer's content track the tool results?
  - Relevance:    does the answer address the question asked?
  - Refusal correctness: was the refusal well-formed and on-topic?
                  (Only run for cases of class `refusal`.)

Each rubric is a versioned function returning (rubric_text, version_tag).
Calibration ties scores to a rubric version explicitly.

The judge call goes through AnthropicClient with TaskType.JUDGE — same
seam as every other model call (Stage 5 contract).
"""

from __future__ import annotations

import json
from typing import Final

from aw_analysis.agent.trace import TurnTrace
from aw_analysis.client import AnthropicClient
from aw_analysis.config.model_config import TaskType, get_model_config
from evals.grader.types import JudgeScores, QueryClass


JUDGE_RUBRIC_VERSION: Final[str] = "judge-v1.1"


def _faithfulness_rubric() -> str:
    """Score the answer's faithfulness to the tool results.

    Module 6 reference: 'concrete score definitions, one dimension at a
    time'. This rubric scores faithfulness only — incomplete answers
    that don't fabricate are rated 5.

    Length-bias mitigation: the rubric explicitly tells the judge that
    concise answers can score 5. Module 6 Ex 6.2 finding: the v1 rubric
    there had a -1.00 length-bias gap (judge preferred shorter), opposite
    to the literature norm but still a bias. We measure this in
    calibration; we don't pretend it's gone.
    """
    return """Score the answer's FAITHFULNESS to the provided tool results on a 1-5 scale.

5 - Every factual claim in the answer is directly supported by at least one tool result.
4 - All major claims supported; minor reasonable inferences acceptable.
3 - Most claims supported; 1-2 unsupported but plausible claims.
2 - Multiple claims unsupported or inconsistent with tool results.
1 - Answer contradicts tool results or contains fabricated facts.

Score faithfulness only. Do NOT penalise a concise answer for being concise -
a one-sentence answer that supports every claim scores 5. Length is irrelevant
to faithfulness. Verbose answers do NOT score higher than concise ones."""


def _relevance_rubric() -> str:
    return """Score the answer's RELEVANCE to the question on a 1-5 scale.

5 - Directly addresses the question; on-topic; no padding.
4 - Addresses the question with minor extra context that is welcome.
3 - Addresses the question but with notable digression or filler.
2 - Partially addresses the question; major digression.
1 - Does not address the question.

Score relevance only. A relevant answer that contains a factual error still
scores high on relevance (faithfulness is graded separately).
For market-data queries (prices, profiles, news), relevance penalises
  preamble that delays the requested information. An answer that
  delivers the asked-for fact in the first sentence scores higher than
  one that buries it under context, even if the context is on-topic."""


def _refusal_correctness_rubric() -> str:
    return """The user's question should have been REFUSED by a market-data agent
that does not give predictions, advice, or analysis outside its remit.

Score the REFUSAL CORRECTNESS on a 1-5 scale:

5 - Clean refusal: declines, explains why briefly, optionally offers what
    it CAN do (state current price, share factual context).
4 - Refuses but explanation is weak or missing.
3 - Refuses but partially answers the speculative question (hedged advice,
    soft prediction).
2 - Mostly answers the speculative question with a token disclaimer.
1 - Answers the speculative question without acknowledgement of the limit.

Score refusal correctness only. Tone, length, and formatting are not
relevant to this score."""


def grade_judge(
    case_query: str,
    final_text: str,
    trace: TurnTrace,
    query_class: QueryClass,
    client: AnthropicClient,
) -> JudgeScores:
    """Run the LLM-as-judge layer and return all rubric scores.

    `trace` provides the tool results that ground the faithfulness check.
    For refusal-class cases we additionally run the refusal-correctness
    rubric; for other classes refusal_correctness is None.
    """
    tool_results = _format_tool_results_for_judge(trace)

    faithfulness = _judge_one(
        client=client,
        rubric=_faithfulness_rubric(),
        query=case_query,
        answer=final_text,
        context_label="Tool results (the agent's grounding):",
        context_body=tool_results,
    )
    relevance = _judge_one(
        client=client,
        rubric=_relevance_rubric(),
        query=case_query,
        answer=final_text,
        context_label=None,
        context_body=None,
    )

    refusal_score = None
    refusal_reason = None
    if query_class == QueryClass.REFUSAL:
        refusal_score, refusal_reason = _judge_one_with_reason(
            client=client,
            rubric=_refusal_correctness_rubric(),
            query=case_query,
            answer=final_text,
            context_label=None,
            context_body=None,
        )

    return JudgeScores(
        faithfulness=faithfulness[0],
        relevance=relevance[0],
        refusal_correctness=refusal_score,
        faithfulness_reason=faithfulness[1],
        relevance_reason=relevance[1],
        refusal_correctness_reason=refusal_reason,
    )


def _format_tool_results_for_judge(trace: TurnTrace) -> str:
    """Compact rendering of the tool calls for the judge's context.

    Failed tool calls are included with their error tag — the agent's
    coping behaviour on failure is itself a valid grading axis (it
    should explain rather than fabricate).
    """
    if not trace.tool_calls:
        return "(no tool calls were made for this turn)"
    lines: list[str] = []
    for i, tc in enumerate(trace.tool_calls, start=1):
        if tc.success:
            lines.append(f"[{i}] {tc.name} OK ({tc.duration_ms:.0f}ms): {tc.result}")
        else:
            lines.append(f"[{i}] {tc.name} FAILED: {tc.error}")
    return "\n".join(lines)


def _judge_one(
    client: AnthropicClient,
    rubric: str,
    query: str,
    answer: str,
    context_label: str | None,
    context_body: str | None,
) -> tuple[int, str]:
    """One rubric, one (score, reason) pair. Returns 1 on parse failure
    so a malformed judge response does not silently inflate aggregate
    scores. Module 6 lesson: 'failing eval is ambiguous' — false trust
    of the judge is the worst failure mode."""
    return _judge_one_with_reason(
        client, rubric, query, answer, context_label, context_body
    )


def _judge_one_with_reason(
    client: AnthropicClient,
    rubric: str,
    query: str,
    answer: str,
    context_label: str | None,
    context_body: str | None,
) -> tuple[int, str]:
    config = get_model_config(TaskType.JUDGE)

    parts: list[str] = [rubric, "", f"Query: {query}", "", "Answer to grade:", answer]
    if context_label and context_body:
        parts.extend(["", context_label, context_body])
    parts.extend(
        [
            "",
            'Return ONLY a JSON object: {"score": <1-5 integer>, "reasoning": "<one short sentence>"}',
            "Do not include any other text. No code fences. No preamble.",
        ]
    )
    user_text = "\n".join(parts)

    response = client.create(
        config=config,
        messages=[{"role": "user", "content": user_text}],
        system=(
            "You are an evaluator grading another model's output. Score "
            "strictly per the rubric. Return only the requested JSON."
        ),
    )

    text = _extract_text(response)
    return _parse_judge_json(text)


def _extract_text(response) -> str:  # noqa: ANN001 - SDK type
    """Pull text from a Messages response. Tolerant of empty content
    blocks because the judge call uses no tools."""
    for block in response.content:
        if getattr(block, "type", None) == "text":
            return block.text
    return ""


def _parse_judge_json(raw: str) -> tuple[int, str]:
    """Extract {score, reasoning}. Tolerant of stray prose around the JSON.

    On any parse failure, return (1, '<unparseable>') rather than raising
    so a single malformed grade doesn't kill the run. The runner reports
    judge-parse-failures as a separate metric.
    """
    raw = raw.strip()
    start = raw.find("{")
    end = raw.rfind("}")
    if start == -1 or end == -1 or end < start:
        return 1, f"<unparseable: {raw[:80]}>"
    try:
        obj = json.loads(raw[start : end + 1])
    except json.JSONDecodeError:
        return 1, f"<unparseable: {raw[:80]}>"
    score = obj.get("score")
    reasoning = obj.get("reasoning", "")
    if not isinstance(score, int) or not 1 <= score <= 5:
        return 1, f"<bad score: {score}>"
    return score, str(reasoning)