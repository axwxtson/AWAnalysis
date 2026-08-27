"""The CLI argument contract.

bin/aw has never had an argument parser: every token after the command
was joined into the user message. The Block 7 probe compares prompt
versions on one fixed string, so the string reaching the model must be
identical in every arm. That makes "the flag does not reach the message"
a correctness condition of the experiment, not a convenience.

Checked offline, before any run spends money. No key, no client, no
network.
"""

from __future__ import annotations

import pytest

from aw_analysis.cli.main import _parse_args
from aw_analysis.prompts import ACTIVE_PROMPT_VERSION, PROMPT_VERSIONS


def test_the_flag_does_not_reach_the_message():
    args = _parse_args(["--prompt-version", "cand-a", "What is Bitcoin?"])
    assert " ".join(args.message) == "What is Bitcoin?"
    assert args.prompt_version == "cand-a"


def test_the_message_is_identical_with_and_without_the_flag():
    """The probe's comparability condition, stated as an assertion."""
    plain = _parse_args(["What is Bitcoin?"])
    flagged = _parse_args(["--prompt-version", "cand-b", "What is Bitcoin?"])
    assert " ".join(plain.message) == " ".join(flagged.message)


def test_unquoted_words_still_join_into_one_message():
    """bin/aw has always accepted an unquoted question. Preserved."""
    args = _parse_args(["What", "is", "Bitcoin?"])
    assert " ".join(args.message) == "What is Bitcoin?"


def test_no_message_means_interactive_mode():
    assert _parse_args([]).message == []


def test_the_default_is_the_active_version():
    assert _parse_args(["hello"]).prompt_version == ACTIVE_PROMPT_VERSION


def test_an_unknown_version_is_rejected_at_parse_time():
    """A typo fails before a turn is billed, not after."""
    with pytest.raises(SystemExit):
        _parse_args(["--prompt-version", "v9.9.9", "hello"])


def test_every_registered_version_is_selectable():
    for version in PROMPT_VERSIONS:
        args = _parse_args(["--prompt-version", version, "hello"])
        assert args.prompt_version == version