"""The CONCEPT adjudication branch.

Three things need pinning, because this branch decides pass/fail on cases
that cost money and it is the only guard against the failure mode the
class exists to catch.

Faithfulness must not gate a CONCEPT case: there are no tool results, so
the rubric has nothing to grade claims against and a low score there is
an artefact of the class, not a failure.

Relevance must gate it. That is the hedge detector, and it is the first
place relevance decides anything in this suite.

And the deterministic layer must still bite, so a CONCEPT case that calls
a tool fails on the P0 assertion rather than being waved through by a
class-specific branch.
"""

from evals.grader.types import (
    Assertion,
    AssertionKind,
    AssertionResult,
    EvalCase,
    JudgeScores,
    QueryClass,
    Severity,
)
from evals.runner.run import _adjudicate


def _case(query_class=QueryClass.CONCEPT):
    return EvalCase(
        id="concept_stub",
        query="What is proof of stake?",
        query_class=query_class,
        assertions=[
            Assertion(
                kind=AssertionKind.NOT_REFUSED,
                target="",
                severity=Severity.P0,
                description="a legitimate concept question must be answered",
            )
        ],
        rationale="stub case for the adjudication branch, not a golden case",
    )


def _scores(*, faithfulness=1, relevance=5):
    return JudgeScores(
        faithfulness=faithfulness,
        relevance=relevance,
        faithfulness_reason="no tool results to ground against",
        relevance_reason="stub",
    )


def _passing_assertion():
    return AssertionResult(
        assertion=_case().assertions[0],
        passed=True,
        detail="stub",
    )


def test_faithfulness_does_not_gate_a_concept_case():
    """Faithfulness 1 with high relevance still passes.

    A CONCEPT answer cites no tool results, so every claim in it looks
    unsupported to the faithfulness rubric. Gating on it would fail the
    whole class for a reason unrelated to what the class measures. Same
    argument the REFUSAL branch already makes.
    """
    passed, summary = _adjudicate(
        _case(), [_passing_assertion()], _scores(faithfulness=1, relevance=5)
    )

    assert passed, summary


def test_low_relevance_fails_a_concept_case():
    """The hedge detector.

    NOT_REFUSED passes here, which is the point: the classifier sees no
    refusal because none was uttered. Relevance 2 is a thin answer that
    changes the subject, and it is the only signal that catches it.
    """
    passed, summary = _adjudicate(
        _case(), [_passing_assertion()], _scores(relevance=2)
    )

    assert not passed
    assert "relevance=2" in summary


def test_a_failed_p0_assertion_still_fails_a_concept_case():
    """The class-specific branch must not shadow the deterministic layer."""
    failing = AssertionResult(
        assertion=_case().assertions[0],
        passed=False,
        detail="stub",
    )

    passed, summary = _adjudicate(_case(), [failing], _scores(relevance=5))

    assert not passed
    assert "P0 deterministic failures" in summary