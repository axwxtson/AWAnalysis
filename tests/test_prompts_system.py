"""Pinning tests for the registered system prompt versions.

Prompt versions are immutable audit artefacts. Two things need proving
and neither is provable by reading a diff:

1. That a committed version's rendered bytes have not moved. The Block 6
   comparison pairs a sealed v2.5.0 red-team run against a v2.6.0 run,
   and both arms are only comparable if v2.5.0's text is the text that
   was measured. A whitespace edit inside its string literal would be
   invisible in review and would silently invalidate the pairing.

2. That a version bump changed only the sections it claims to. The
   cheap evidence for that is byte-identity of the reused sections,
   which is only available because they were reused rather than edited.

No network, no credentials. These are pure functions over strings.
"""

from __future__ import annotations

import difflib
import hashlib

from aw_analysis.prompts.examples import render_examples_v2_5_0
from aw_analysis.prompts.system import (
    _critical_rules_restated,
    _how_to_think,
    _how_to_use_tools,
    _identity_v2_5_0,
    _identity_v2_6_0,
    _output_contract,
    _refusal_policy_v2_5_0,
    _refusal_policy_v2_6_0,
    _scope_test_v2_6_0,
    _tool_selection_v2_5_0,
    _tool_selection_v2_6_0,
)
from aw_analysis.prompts.versions import PROMPT_VERSIONS

# Sections v2.6.0 reuses from v2.5.0 without modification.
SHARED_SECTIONS = (
    _how_to_think,
    _how_to_use_tools,
    _output_contract,
    render_examples_v2_5_0,
    _critical_rules_restated,
)

# Sections v2.6.0 introduces.
NEW_SECTIONS = (
    _scope_test_v2_6_0,
    _tool_selection_v2_6_0,
    _refusal_policy_v2_6_0,
)


# --- registry ----------------------------------------------------------

def test_registry_holds_the_ten_known_versions():
    """A count, not a grep.

    PROMPT_VERSIONS is populated by import side effect across two
    modules: the @register decorators in system.py, plus one in
    v2_3_0_broken.py that prompts/__init__.py imports for the Stage 6
    regression demo. Its size is not derivable from any single file.

    Block 7 added cand-a and cand-b, then v2.7.0 promoting cand-a. All
    three are registered and inert; ACTIVE_PROMPT_VERSION is unchanged.

    Block 9 added cand-c, restating the product limb as a depth ceiling.
    Also inert. If it is promoted the promotion aliases it, so this list
    gains a version and cand-c stays rather than being replaced.
    """
    assert sorted(PROMPT_VERSIONS) == [
        "2.3.0-broken",
        "cand-a",
        "cand-b",
        "cand-c",
        "v2.2.2",
        "v2.3.0",
        "v2.4.0",
        "v2.5.0",
        "v2.6.0",
        "v2.7.0",
    ]


# --- immutability of the measured baseline -----------------------------

def test_v2_5_0_bytes_have_not_moved():
    """v2.5.0 is one arm of the Block 6 paired comparison.

    The hash is of the rendered string, not the source, so it catches a
    whitespace change inside a string literal that ruff cannot see:
    system.py is exempt from W291 and W293 precisely because prompt
    bodies are rendered bytes rather than code.
    """
    digest = hashlib.sha256(PROMPT_VERSIONS["v2.5.0"].encode()).hexdigest()
    assert digest == (
        "33795ee5a9add8a45bb79d0040e19497b885a241bb6b07518dfef949bcbf6737"
    )


def test_v2_6_0_bytes_have_not_moved():
    """Same argument, other arm. Pinned from the commit that shipped it."""
    digest = hashlib.sha256(PROMPT_VERSIONS["v2.6.0"].encode()).hexdigest()
    assert digest == (
        "a6eac9ceced7db9c54ecda6b4efbe953f88f98d366bebf5f59e8c7af0d4dc1d7"
    )


# --- the Block 7 ablation candidates -----------------------------------

def test_candidates_are_v2_6_0_under_the_substitution_they_claim():
    """The single-difference constraint, asserted rather than trusted.

    A digest reports that bytes moved. This reports that the derivation
    is still the derivation, which is the claim the ablation rests on.
    """
    base = PROMPT_VERSIONS["v2.6.0"]
    expected_a = base.replace(
        "a general market, trading or asset concept",
        "a general market or trading concept",
    ).replace(
        "general market, trading and asset concepts",
        "general market and trading concepts",
    )
    expected_b = base.replace(
        "general market, trading and asset concepts", "general concepts"
    )
    assert PROMPT_VERSIONS["cand-a"] == expected_a
    assert PROMPT_VERSIONS["cand-b"] == expected_b


def test_cand_a_bytes_have_not_moved():
    """Pinned before the probe runs, so an arm cannot be relabelled after
    a result is seen."""
    digest = hashlib.sha256(PROMPT_VERSIONS["cand-a"].encode()).hexdigest()
    assert digest == (
        "2be3bd509abc028b3325fe351361c6609ae73f3775986ac67b88969561e79458"
    )


def test_cand_b_bytes_have_not_moved():
    """Same argument, other candidate."""
    digest = hashlib.sha256(PROMPT_VERSIONS["cand-b"].encode()).hexdigest()
    assert digest == (
        "76b1615ec6a074c7e3178af497d52d7e3469236b4d76b350aa52ed1933e09d3d"
    )


def test_v2_7_0_is_byte_identical_to_the_arm_that_was_measured():
    """v2.7.0 aliases cand-a, and the alias is asserted, not assumed.

    Every result licensing this version was measured under the key
    cand-a. If the two ever render different bytes, the evidence and the
    shipped prompt have come apart, which is the 8026830 failure.
    """
    assert PROMPT_VERSIONS["v2.7.0"] == PROMPT_VERSIONS["cand-a"]


def test_v2_7_0_bytes_have_not_moved():
    """Same digest as cand-a, spelled out rather than derived, so this
    test fails independently of the identity assertion above."""
    digest = hashlib.sha256(PROMPT_VERSIONS["v2.7.0"].encode()).hexdigest()
    assert digest == (
        "2be3bd509abc028b3325fe351361c6609ae73f3775986ac67b88969561e79458"
    )


# --- what v2.6.0 reuses ------------------------------------------------

def test_v2_6_0_reuses_the_shared_sections_byte_identically():
    built = PROMPT_VERSIONS["v2.6.0"]
    missing = [f.__name__ for f in SHARED_SECTIONS if f() not in built]
    assert missing == []


def test_shared_sections_are_byte_identical_across_both_versions():
    """The reuse only counts as evidence if both versions carry the
    same bytes. A section rebuilt rather than reused would pass the
    test above and still break attribution.
    """
    v5, v6 = PROMPT_VERSIONS["v2.5.0"], PROMPT_VERSIONS["v2.6.0"]
    absent = [f.__name__ for f in SHARED_SECTIONS if f() not in v5 or f() not in v6]
    assert absent == []


# --- what v2.6.0 replaces ----------------------------------------------

def test_v2_6_0_carries_the_new_sections():
    built = PROMPT_VERSIONS["v2.6.0"]
    missing = [f.__name__ for f in NEW_SECTIONS if f() not in built]
    assert missing == []
    assert _identity_v2_6_0() in built


def test_v2_6_0_does_not_carry_the_sections_it_replaces():
    """Absence check, the half a presence check cannot do.

    _identity_v2_5_0 is deliberately excluded: v2.6.0's identity section
    appends the self-description contract to text that is otherwise
    identical, so the v2.5.0 string is a proper prefix of the v2.6.0 one
    and substring-absence is not a valid discriminator for it. The
    discriminator for identity is the added subsection, asserted below.
    """
    built = PROMPT_VERSIONS["v2.6.0"]
    assert _tool_selection_v2_5_0() not in built
    assert _refusal_policy_v2_5_0() not in built


def test_v2_5_0_does_not_carry_the_new_sections():
    """Guards the other direction: a section helper accidentally wired
    into the v2.5.0 builder would change the sealed baseline.
    """
    v5 = PROMPT_VERSIONS["v2.5.0"]
    present = [f.__name__ for f in NEW_SECTIONS if f() in v5]
    assert present == []
    assert "## Describing yourself" not in v5
    assert "## Describing yourself" in PROMPT_VERSIONS["v2.6.0"]


def test_identity_v2_6_0_extends_v2_5_0_rather_than_rewriting_it():
    """Pins the prefix relationship the absence test above relies on.

    If identity is ever rewritten rather than extended, this fails and
    the exclusion documented in that test stops being justified.
    """
    assert _identity_v2_6_0().startswith(_identity_v2_5_0())


# --- section ordering --------------------------------------------------

def test_scope_test_precedes_the_thinking_scaffold():
    """_how_to_think step 1 asks a subject-only question. It is reused
    unchanged so that byte-identity remains available as evidence in the
    section governing tool planning, where the compound cases live. The
    mismatch is resolved by position: the scope test is stated as a gate
    applied before anything else, above the scaffold.
    """
    built = PROMPT_VERSIONS["v2.6.0"]
    assert built.index(_scope_test_v2_6_0()) < built.index(_how_to_think())
    assert built.startswith(_identity_v2_6_0())


# --- the two edits, at line granularity --------------------------------

def _hunks(before: str, after: str) -> list[str]:
    return [
        line
        for line in difflib.unified_diff(
            before.splitlines(), after.splitlines(), lineterm="", n=0
        )
        if line.startswith("@@")
    ]


def test_tool_selection_changes_exactly_the_no_tool_clause():
    """The v2.6.0 tool-selection section is a 94-line hand copy of the
    v2.5.0 one. A copy is where a plausible-but-wrong substitution lands
    without changing the shape, so the test asserts the diff rather than
    the result.
    """
    before, after = _tool_selection_v2_5_0(), _tool_selection_v2_6_0()
    assert len(_hunks(before, after)) == 1
    changed = [
        line
        for line in difflib.unified_diff(
            before.splitlines(), after.splitlines(), lineterm="", n=0
        )
        if line.startswith("+") and not line.startswith("+++")
    ]
    assert len(changed) == 1
    assert "**No tool**" in changed[0]
    assert "the scope test applies" in changed[0]


def test_refusal_policy_adds_one_bullet_and_removes_nothing():
    before, after = _refusal_policy_v2_5_0(), _refusal_policy_v2_6_0()
    diff = list(
        difflib.unified_diff(
            before.splitlines(), after.splitlines(), lineterm="", n=0
        )
    )
    removed = [
        line for line in diff if line.startswith("-") and not line.startswith("---")
    ]
    added = [
        line for line in diff if line.startswith("+") and not line.startswith("+++")
    ]
    assert removed == []
    assert len(added) == 1
    assert "fails the scope test" in added[0]


# --- assertions other instruments depend on ----------------------------

def test_refusal_policy_v2_6_0_keeps_the_etf_line():
    """refusal_etf_spy is the only golden refusal case that asserts on
    output content (OUTPUT_CONTAINS "ETF") rather than on the refusal
    flag, which makes it the one case in that class that can detect an
    over-refusal. Its assertion runs off this text.
    """
    assert "ETFs, indices, forex, or " in _refusal_policy_v2_6_0()


def test_refusal_policy_v2_6_0_keeps_the_state_what_you_can_do_close():
    """Both instruments in Block 6 are monotone in refusal: neither the
    golden suite nor the red-team judge scores an over-refusal worse.
    This closing instruction is the only thing in the prompt pushing the
    other way, so it is pinned rather than left to review.
    """
    assert "state what you can" in _refusal_policy_v2_6_0()


def test_self_description_names_no_tool():
    """The contract's value is that leaking it verbatim still grades as
    defended, which requires it to disclose nothing the exfiltration
    rubric treats as a leak. The tool names appear elsewhere in the
    prompt by necessity; they must not appear after the contract's
    heading.
    """
    contract = _identity_v2_6_0().split("## Describing yourself", 1)[1]
    for tool in (
        "get_crypto_price",
        "get_equity_price",
        "lookup_asset_profile",
        "web_search",
    ):
        assert tool not in contract, tool

def test_active_version_is_not_the_deliberately_broken_one():
    """ACTIVE_PROMPT_VERSION is the rollback lever, so it is not pinned
    to a value: an incident rollback should not need a test edit.

    What is pinned is that it resolves, and that it is not
    2.3.0-broken. That version has the whole refusal section removed and
    exists for the Stage 6 regression demo. Routing production to it
    fails nothing loudly: it builds, it imports, the agent runs, and
    every refusal case quietly stops passing.
    """
    from aw_analysis.prompts.versions import ACTIVE_PROMPT_VERSION

    assert ACTIVE_PROMPT_VERSION in PROMPT_VERSIONS
    assert ACTIVE_PROMPT_VERSION != "2.3.0-broken"