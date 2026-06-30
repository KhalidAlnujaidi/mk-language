"""Tests for products/groom/stages/deslop.py — the stop-slop detector.

Pure, deterministic, model-free (thesis #1). Fail-direction SOFT (thesis #2):
the detector only reports; callers decide what to do.
"""

from __future__ import annotations

from kernel.contracts import FailDirection
from products.groom.stages import deslop


def test_clean_text_scores_one_and_is_clean() -> None:
    r = deslop.find_slop("Add a login endpoint and a test for it.")
    assert r.clean is True
    assert r.found == ()
    assert r.score == 1.0


def test_single_tell_is_flagged_and_scored() -> None:
    r = deslop.find_slop("Let me be clear: this refactors the parser.")
    assert r.clean is False
    assert "throat_clearing" in r.found
    assert r.score == 0.8  # 1.0 - 0.2 * 1


def test_multiple_distinct_tells_compound_toward_zero() -> None:
    text = (
        "Let me be clear. It's important to note that we should dive into "
        "the code. In conclusion, as an AI I hope this helps."
    )
    r = deslop.find_slop(text)
    assert len(r.found) >= 4
    assert r.score <= 0.2


def test_detection_is_case_insensitive() -> None:
    assert deslop.find_slop("IN CONCLUSION, ship it.").clean is False


def test_fail_direction_is_soft() -> None:
    assert deslop.FAIL_DIRECTION is FailDirection.SOFT
