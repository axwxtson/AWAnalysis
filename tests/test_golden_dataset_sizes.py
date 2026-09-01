"""Suite sizes, pinned rather than remembered.

Three datasets whose counts are quoted separately and must never be
added together. Nothing enforced that before this file, which left a
standing constraint resting on whoever was reading at the time.

The general count moved from 6 to 10 in Block 9 when the product-limb
cases landed, so any comparison against a general figure recorded
earlier uses the original six. A failure here is a prompt to re-derive
every quoted figure, not to update the number and move on.
"""
from __future__ import annotations

from evals.golden import ASSET_CLASSES, cases_for


def test_the_suites_have_the_sizes_that_get_quoted() -> None:
    assert len(cases_for("crypto")) == 23
    assert len(cases_for("equities")) == 16
    assert len(cases_for("general")) == 10


def test_the_asset_suites_total_thirty_nine() -> None:
    """The figure quoted as the golden suite. General is excluded from
    it deliberately and is reported on its own."""
    assert len(cases_for("crypto")) + len(cases_for("equities")) == 39


def test_no_case_id_appears_in_two_suites() -> None:
    ids = [case.id for name in ASSET_CLASSES for case in cases_for(name)]

    assert len(ids) == len(set(ids))