"""Tests for the ``slop`` eval assertion kind (stop-slop harvest).

The checker reuses products/groom/stages/deslop.find_slop, so a runtime groom
flag and a regression assertion share one ground truth (thesis #1).
"""

from __future__ import annotations

from evals.checkers import check
from evals.schema import Assertion


def test_slop_is_a_valid_kind() -> None:
    # Construction validates the kind against VALID_ASSERTION_KINDS.
    Assertion(kind="slop", target="response_text", expected="")


def test_clean_output_passes() -> None:
    a = Assertion(kind="slop", target="response_text", expected="")
    r = check(a, "Refactored the parser; added a regression test.")
    assert r.passed is True
    assert r.score == 1.0
    assert "free of slop" in r.reason


def test_slop_output_fails_and_names_the_tells() -> None:
    a = Assertion(kind="slop", target="response_text", expected="")
    r = check(a, "In conclusion, as an AI I hope this helps.")
    assert r.passed is False
    assert r.score < 1.0
    assert "in_conclusion" in r.reason or "as_an_ai" in r.reason
