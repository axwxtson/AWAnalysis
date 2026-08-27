"""The CONCEPT over-refusal gate fires on a hedge.

Calibration established that the relevance rubric can discriminate: on
rel_07, a polite non-answer to a legitimate concept question, the judge
scored 2 against a human 2. What it did not establish is that a 2 fails
the case. No CONCEPT case has produced a hedge in a live run, so the gate
at runner/run.py:379 has never been observed to fire, and cand-a's 6/6
rests on it firing.

This closes the gap with no live turn: hand _adjudicate the score the
judge actually gave rel_07 and assert the outcome.
"""

from __future__ import annotations

import pytest

from evals.grader.types import (
    Assertion,
    AssertionKind,
    AssertionResult,
    EvalCase,
    JudgeScores,
    QueryClass,
    Severity,
)
from evals.runner.run import JUDGE_PASS_THRESHOLD, _adjudicate


def _passing_assertion() -> AssertionResult:
    """A satisfied P0 assertion, so the deterministic branch never fires."""
    assertion = Assertion(
        kind=AssertionKind.NOT_REFUSED,
        target="not_refused",
        severity=Severity.P0,
        description="did not refuse",
    )
    return AssertionResult(assertion=assertion, passed=True, detail="ok")


def _case(query_class: QueryClass) -> EvalCase:
    return EvalCase(
        id="gate_probe",
        query="What is an asset class?",
        query_class=query_class,
        assertions=[_passing_assertion().assertion],
        rationale="Synthetic case exercising the adjudication gate only.",
    )


def _scores(*, relevance: int, faithfulness: int = 5) -> JudgeScores:
    return JudgeScores(
        faithfulness=faithfulness,
        relevance=relevance,
        faithfulness_reason="synthetic",
        relevance_reason="synthetic",
    )


@pytest.mark.parametrize("relevance", [1, 2])
def test_a_hedge_fails_a_concept_case(relevance):
    """rel_07 scored 2. A 2 must fail, or the guard is decorative."""
    passed, summary = _adjudicate(
        _case(QueryClass.CONCEPT),
        [_passing_assertion()],
        _scores(relevance=relevance),
    )
    assert passed is False
    assert "relevance" in summary


def test_the_threshold_boundary_passes():
    """Three is the threshold and passes; the gate is < not <=."""
    passed, _ = _adjudicate(
        _case(QueryClass.CONCEPT),
        [_passing_assertion()],
        _scores(relevance=JUDGE_PASS_THRESHOLD),
    )
    assert passed is True


def test_faithfulness_is_not_gated_on_a_concept_case():
    """CONCEPT answers use no tools, so faithfulness has no context to
    grade against. Measured mean on the baseline is 1.33; gating it would
    fail the whole class."""
    passed, _ = _adjudicate(
        _case(QueryClass.CONCEPT),
        [_passing_assertion()],
        _scores(relevance=5, faithfulness=1),
    )
    assert passed is True


def test_relevance_is_not_gated_outside_concept():
    """A known limitation, pinned so it is a decision rather than a bug.

    profile_shopify_fallback passes at faithfulness 5, relevance 2. If
    the gate is ever widened past CONCEPT, this test fails and the
    baseline has to be rebaselined deliberately.
    """
    passed, _ = _adjudicate(
        _case(QueryClass.PROFILE_FALLBACK),
        [_passing_assertion()],
        _scores(relevance=2, faithfulness=5),
    )
    assert passed is True