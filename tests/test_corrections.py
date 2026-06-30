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


# ---------------------------------------------------------------------------
# Fix 4: additional boundary chars (? and ;) + multi-word cue
# ---------------------------------------------------------------------------


def test_question_mark_boundary_is_a_correction() -> None:
    """'no?' should match the 'no' cue with '?' as a boundary char."""
    assert looks_like_correction("do x", "no? that's wrong") is True


def test_semicolon_boundary_is_a_correction() -> None:
    """'no; use X' should match the 'no' cue with ';' as a boundary char."""
    assert looks_like_correction("do x", "no; use sqlite") is True


def test_multi_word_cue_i_meant_is_a_correction() -> None:
    """Multi-word cue 'i meant' must be detected."""
    assert looks_like_correction("use the toolbar", "i meant the sidebar") is True


def test_nominal_word_boundary_still_not_a_correction() -> None:
    """'nominal' must not match 'no' — the word-boundary guard must stay green."""
    assert looks_like_correction("do x", "nominal behaviour is fine") is False
