"""The run artefact's prompt digest.

Pins the serialiser, not the construction site. run_suite builds the
RunReport inside a function that also builds a live client, so the line
that computes the digest from system_prompt cannot be exercised offline.
That gap is real and named rather than papered over: what is pinned here
is that the field survives serialisation and that a disagreement between
label and digest is visible.
"""

from aw_analysis.prompts.versions import PROMPT_VERSIONS, prompt_digest
from evals.runner.run import RunReport, report_to_dict


def _report(**overrides):
    kwargs = {
        "run_id": "t",
        "prompt_version": "v2.5.0",
        "prompt_sha256": prompt_digest(PROMPT_VERSIONS["v2.5.0"]),
        "judge_rubric_version": "stub",
    }
    kwargs.update(overrides)
    return RunReport(**kwargs)


def test_the_digest_survives_serialisation():
    report = _report()
    assert report_to_dict(report)["prompt_sha256"] == report.prompt_sha256


def test_a_mislabelled_artefact_is_detectable():
    """8026830 expressed as a test.

    That commit changed what v2.5.0 renders to between two runs both
    labelled v2.5.0. The label agreed with itself and nothing could catch
    it. Here the label claims v2.5.0 while the digest is v2.6.0's, and the
    disagreement is visible from the artefact alone, which is the whole
    reason the field exists.
    """
    report = _report(prompt_sha256=prompt_digest(PROMPT_VERSIONS["v2.6.0"]))
    d = report_to_dict(report)

    assert d["prompt_sha256"] != prompt_digest(PROMPT_VERSIONS[d["prompt_version"]])