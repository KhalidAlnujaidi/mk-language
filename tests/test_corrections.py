"""Tests for the free-label correction heuristic (thesis #3)."""

from __future__ import annotations

from kernel.corrections import looks_like_correction


def test_short_no_prefixed_followup_is_a_correction() -> None:
    assert looks_like_correction(
        "add a logout button", "no, put it in the navbar"
    ) is True


def test_actually_prefix_is_a_correction() -> None:
    assert looks_like_correction("use postgres", "actually use sqlite") is True


def test_long_followup_is_not_a_correction() -> None:
    long = "actually " + " ".join(["word"] * 30)
    assert looks_like_correction("do x", long) is False


def test_cue_must_be_a_word_not_a_prefix() -> None:
    # 'no' inside 'nominal' must not match
    assert looks_like_correction("do x", "nominal behaviour is fine") is False


def test_unrelated_followup_is_not_a_correction() -> None:
    assert looks_like_correction("add tests", "now add docs too") is False


def test_empty_prev_is_never_a_correction() -> None:
    assert looks_like_correction("", "no") is False


def test_case_insensitive() -> None:
    assert looks_like_correction("x", "NOPE") is True
