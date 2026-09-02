"""Offline tests for the red-team re-grade tool.

No network, no credentials, no judge calls. The grader is injected, so
record assembly is exercised without paying for anything.

Tests one to five use a synthetic attack rather than a real one.
Replacing bnd_08's indicator lists is filed work, and a plumbing test
that hard-codes those lists would break for a reason unrelated to
plumbing. Test six uses the real registry because the property it pins
is about the registry, and it asserts movement rather than a fixed
digest so that it survives the change it is designed to catch.
"""

from __future__ import annotations

import copy
import json

import pytest

import evals.redteam.regrade as regrade_module
from evals.redteam.attacks import ATTACKS
from evals.redteam.grader import REDTEAM_RUBRIC_VERSION, rubric_digest
from evals.redteam.regrade import (
    attack_digest,
    build_envelope,
    load_source,
    regrade_records,
    resolve_attack,
    source_prompt_digest,
)

_ATTACK = {
    "id": "syn_01_fixture",
    "category": "boundary",
    "severity": "low",
    "description": "Synthetic attack, fixture only",
    "injection_target": "user",
    "payload": "fixture payload",
    "expected_behaviour": "refuse",
    "success_indicators": ["alpha", "beta"],
    "failure_indicators": ["gamma"],
}


def _record(replicate: int = 1, verdict: str = "defended") -> dict:
    """One record shaped like a red-team run artefact's."""
    return {
        "attack_id": _ATTACK["id"],
        "attack_payload": _ATTACK["payload"],
        "prompt_sha256": "2be3bd50",
        "replicate": replicate,
        "response": {"answer": "alpha only"},
        "grade": {"final_verdict": verdict, "deterministic": {"verdict": verdict}},
    }


def _stub_grade(attack: dict, response: dict) -> dict:
    """Stand in for grade_attack. Returns the opposite of the fixture's verdict."""
    return {"final_verdict": "compromised", "deterministic": {"verdict": "compromised"}}


@pytest.fixture
def registry(monkeypatch):
    """Point the module's ATTACKS at the synthetic attack alone."""
    monkeypatch.setattr(regrade_module, "ATTACKS", [_ATTACK])
    return _ATTACK


# --- The envelope -------------------------------------------------------

def test_envelope_records_both_instruments_and_its_own_source(registry, tmp_path):
    """Every fact true of the whole file, and records last.

    Both instruments are named because both can move independently: the
    rubric set by an edit to CATEGORY_RUBRICS, the attack by an edit to
    its indicator lists. An artefact naming only one leaves the other
    silent.

    source_artefact is a bare filename. A stored path would commit one
    machine's layout into a shared artefact.
    """
    source = tmp_path / "v2.7.0_20260901T165056.json"
    records = [_record(replicate=1), _record(replicate=2)]
    regraded = regrade_records(records, registry, grader=_stub_grade)
    env = build_envelope(source, records, registry, regraded, "2026-09-02T00:00:00+00:00")

    assert env["source_artefact"] == "v2.7.0_20260901T165056.json"
    assert "/" not in env["source_artefact"]
    assert env["attack_id"] == "syn_01_fixture"
    assert env["prompt_sha256"] == "2be3bd50"
    assert env["rubric_version"] == REDTEAM_RUBRIC_VERSION
    assert env["rubric_sha256"] == rubric_digest()
    assert env["attack_sha256"] == attack_digest(registry)
    assert list(env)[-1] == "records"


# --- Record assembly ----------------------------------------------------

def test_every_source_record_produces_one_regraded_record(registry):
    """N in, N out, with the old verdict kept beside the new one.

    Both verdicts live in one file so a reader never has to hold two
    open to see what the instrument change did. Absent replicate reads
    as 1, the convention main.py already fixes for artefacts written
    before Block 6.
    """
    records = [_record(replicate=i) for i in (1, 2, 3)]
    out = regrade_records(records, registry, grader=_stub_grade)

    assert len(out) == 3
    assert [r["replicate"] for r in out] == [1, 2, 3]
    assert all(r["source_grade"]["final_verdict"] == "defended" for r in out)
    assert all(r["grade"]["final_verdict"] == "compromised" for r in out)

    without = _record()
    del without["replicate"]
    assert regrade_records([without], registry, grader=_stub_grade)[0]["replicate"] == 1


def test_indicator_lists_live_in_the_envelope_and_not_on_records(registry, tmp_path):
    """Once per file, not once per replicate.

    The lists are identical across every replicate of one attack, so ten
    copies is ten chances to disagree. That is the drift removed from
    tools_called in Stage 2 by deriving one from the other.

    Asserts absence from the records, not only presence in the envelope.
    A test that only checked presence would pass with both.

    The lists are copied rather than referenced, so mutating the
    artefact cannot reach back into the registry.
    """
    records = [_record()]
    regraded = regrade_records(records, registry, grader=_stub_grade)
    env = build_envelope(tmp_path / "src.json", records, registry, regraded, "t")

    assert env["success_indicators"] == ["alpha", "beta"]
    assert env["failure_indicators"] == ["gamma"]
    for record in env["records"]:
        assert "success_indicators" not in record
        assert "failure_indicators" not in record

    env["success_indicators"].append("delta")
    assert registry["success_indicators"] == ["alpha", "beta"]


# --- Refusals -----------------------------------------------------------

def test_an_attack_the_registry_no_longer_holds_refuses(registry):
    """Nothing to grade against, and nothing to digest.

    Also covers records spanning two attacks, which one envelope cannot
    describe: a single attack digest and a single pair of indicator
    lists would be true of neither.
    """
    absent = _record()
    absent["attack_id"] = "syn_99_absent"
    with pytest.raises(ValueError, match="exactly one ATTACKS entry"):
        resolve_attack([absent])

    with pytest.raises(ValueError, match="records for one attack"):
        resolve_attack([_record(), absent])


def test_a_changed_attack_a_mixed_arm_or_a_regrade_as_input_all_refuse(registry, tmp_path):
    """Three ways the input is not what it claims, all silent if unchecked.

    A payload that has moved since the run means the stored responses
    answer a different question, so this is not a re-grade. Two prompt
    digests mean two arms in one file, which makes a single-arm envelope
    a lie. A dict top level means a re-grade was passed as a source,
    which would grade grades rather than responses.
    """
    changed = _record()
    changed["attack_payload"] = "edited since the run"
    with pytest.raises(ValueError, match="differs from the registry"):
        resolve_attack([changed])

    mixed = [_record(), _record()]
    mixed[1]["prompt_sha256"] = "da921768"
    with pytest.raises(ValueError, match="more than one prompt"):
        source_prompt_digest(mixed)

    as_input = tmp_path / "regrade_something.json"
    as_input.write_text(json.dumps({"attack_id": "x", "records": []}))
    with pytest.raises(ValueError, match="not a red-team run artefact"):
        load_source(as_input)


# --- The digest property ------------------------------------------------

def test_attack_digest_tracks_the_attack_read_not_the_whole_registry(monkeypatch):
    """The reason the digest is over one attack rather than over ATTACKS.

    A whole-registry digest would move whenever any unrelated attack was
    edited, making the field noise rather than evidence. Resolution goes
    through resolve_attack rather than digesting a literal, or the first
    half would be true by construction and pin nothing.

    Asserts movement, not a value, so it survives the indicator-list
    replacement it exists to catch.
    """
    bnd_08 = next(a for a in ATTACKS if a["id"] == "bnd_08_prose_artefact")
    baseline = attack_digest(bnd_08)

    elsewhere = copy.deepcopy(ATTACKS)
    for attack in elsewhere:
        if attack["id"] != "bnd_08_prose_artefact":
            attack["success_indicators"] = ["edited elsewhere"]
    monkeypatch.setattr(regrade_module, "ATTACKS", elsewhere)
    record = {"attack_id": "bnd_08_prose_artefact", "attack_payload": bnd_08["payload"]}
    assert attack_digest(resolve_attack([record])) == baseline

    its_own = copy.deepcopy(bnd_08)
    its_own["success_indicators"] = ["smoothing recurrence"]
    assert attack_digest(its_own) != baseline