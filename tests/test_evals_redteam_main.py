"""Selection and replication logic for the red-team runner.

build_run_plan is the only part of main.py testable offline; everything
else makes live calls. It is pinned because the sealed Block 6
measurement selects attacks by id and repeats them, and a wrong
selection is only visible after the run has been paid for.
"""

from __future__ import annotations

import pytest

from evals.redteam.attacks import ATTACKS
from evals.redteam.main import build_run_plan, print_replicates

_FAKE = [
    {"id": "a1", "category": "boundary", "severity": "low"},
    {"id": "a2", "category": "boundary", "severity": "medium"},
    {"id": "a3", "category": "exfiltration", "severity": "medium"},
]


def test_no_filters_returns_every_attack_once():
    plan = build_run_plan(_FAKE)
    assert [a["id"] for a, _ in plan] == ["a1", "a2", "a3"]
    assert {r for _, r in plan} == {1}


def test_filters_compose():
    plan = build_run_plan(_FAKE, category="boundary", severity="medium")
    assert [a["id"] for a, _ in plan] == ["a2"]


def test_ids_select_in_list_order_not_argument_order():
    plan = build_run_plan(_FAKE, ids=["a3", "a1"])
    assert [a["id"] for a, _ in plan] == ["a1", "a3"]


def test_unknown_id_raises_rather_than_selecting_nothing():
    with pytest.raises(ValueError, match="nope"):
        build_run_plan(_FAKE, ids=["a1", "nope"])


def test_known_id_excluded_by_another_filter_is_not_an_error():
    assert build_run_plan(_FAKE, ids=["a3"], category="boundary") == []


def test_replicates_are_cycled_not_blocked():
    plan = build_run_plan(_FAKE, ids=["a1", "a2"], repeat=3)
    assert [(a["id"], r) for a, r in plan] == [
        ("a1", 1),
        ("a2", 1),
        ("a1", 2),
        ("a2", 2),
        ("a1", 3),
        ("a2", 3),
    ]


def test_repeat_below_one_raises():
    with pytest.raises(ValueError):
        build_run_plan(_FAKE, repeat=0)


def test_replicate_tally_excludes_non_delivered(capsys):
    """The denominator is delivered replicates, matching measured().

    An undelivered document attack tested nothing. Counting it would
    report a defence for a replicate the payload never reached.
    """

    def rec(verdict, replicate, delivered):
        return {
            "attack": {"id": "inj_05_doc_payload", "category": "injection", "severity": "critical"},
            "replicate": replicate,
            "response": {"poison_delivered": delivered},
            "grade": {"final_verdict": verdict},
            "latency": 0.0,
        }

    print_replicates(
        [
            rec("defended", 1, True),
            rec("defended", 2, False),
            rec("compromised", 3, True),
        ]
    )
    out = capsys.readouterr().out
    assert "1/2 defended" in out
    assert "split" in out


def test_replicate_tally_flags_only_split_results(capsys):
    def rec(attack_id, verdict, replicate):
        return {
            "attack": {"id": attack_id, "category": "boundary", "severity": "low"},
            "replicate": replicate,
            "response": {"poison_delivered": None},
            "grade": {"final_verdict": verdict},
            "latency": 0.0,
        }

    print_replicates(
        [rec("all_defended", "defended", r) for r in (1, 2, 3)]
        + [rec("none_defended", "compromised", r) for r in (1, 2, 3)]
    )
    out = capsys.readouterr().out
    assert "3/3 defended" in out
    assert "0/3 defended" in out
    assert "split" not in out


def test_block_six_replicate_set_resolves_against_real_attacks():
    """Couples the replicate set to the attack data.

    A renamed or mistyped id would otherwise surface as a short paid run.
    Same argument as the poison map's coupling test, which caught a
    corrupted id in Block 5 before a run.
    """
    ids = [
        "exf_04_markdown_dump",
        "bnd_04_off_topic",
        "bnd_06_asset_wrapped_task",
        "bnd_07_concept_plus_artefact",
        "exf_05_boundary_enumeration",
    ]
    plan = build_run_plan(ATTACKS, ids=ids, repeat=5)
    assert len(plan) == 25
    assert {a["id"] for a, _ in plan} == set(ids)