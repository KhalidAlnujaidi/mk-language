"""Stage: deslop — deterministic detection of LLM "slop" phrasing.

Harvested from ``cheatcodes/stop-slop`` (its ``references/phrases.md`` /
``references/structures.md`` catalogue the tells). The reusable piece is the
*phrase ground truth*, not the skill wrapper — so this is a pure, model-free
detector (thesis #1: a fixed list of tells is ground truth; no model needed to
spot "let me be clear").

Two consumers share this one source of truth (thesis #1, one ground truth):
  - the groom pipeline runs :func:`find_slop` as a SOFT stage that *flags*
    (never silently rewrites) slop in the working text;
  - the eval harness's ``slop`` assertion kind reuses :func:`find_slop` so a
    runtime check and a regression check can never disagree.

Fail-direction is SOFT (thesis #2): this is an optimizer/cleaner, so on any
doubt it passes the text through unchanged and merely annotates.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from kernel.contracts import FailDirection

FAIL_DIRECTION: FailDirection = FailDirection.SOFT

# Throat-clearing / filler tells as (label, raw regex). Kept deliberately
# conservative — only phrases that are near-universally slop, so the SOFT stage
# stays a high-signal flag rather than a noisy nag. Compiled once, below,
# case-insensitively and word-boundaried.
_SLOP_RAW: tuple[tuple[str, str], ...] = (
    ("throat_clearing", r"\blet me (?:be clear|start by|begin by)\b"),
    ("its_important", r"\bit'?s (?:important|worth noting|crucial) (?:to|that)\b"),
    ("in_conclusion", r"\bin (?:conclusion|summary)\b"),
    ("dive_deep", r"\b(?:dive|delve|deep dive) (?:deep |deeper )?into\b"),
    ("here_is_what", r"\bhere'?s (?:what|the thing)\b"),
    ("at_the_end_of_day", r"\bat the end of the day\b"),
    ("important_to_note", r"\b(?:please |kindly )?(?:note|bear in mind) that\b"),
    ("i_hope_this", r"\bi hope this (?:helps|message finds you)\b"),
    ("as_an_ai", r"\bas an? (?:ai|language model)\b"),
    ("tapestry", r"\b(?:rich tapestry|navigate the (?:complexities|landscape))\b"),
)

_SLOP_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = tuple(
    (label, re.compile(raw, re.I)) for label, raw in _SLOP_RAW
)


@dataclass(frozen=True)
class SlopResult:
    """The result of a slop scan.

    *found* is the tuple of canonical labels that fired (deduped, in pattern
    order). *score* is 1.0 for clean text and degrades toward 0.0 as more
    distinct tells appear — a graduated signal the eval harness can threshold.
    """

    found: tuple[str, ...]
    score: float

    @property
    def clean(self) -> bool:
        """True when no slop tell fired."""
        return not self.found


def find_slop(text: str) -> SlopResult:
    """Scan *text* for LLM slop tells. Pure, deterministic, no model call.

    The score is ``1.0`` when clean and drops by ``0.2`` per distinct tell
    (floored at ``0.0``) — so one tell still scores a passing-ish 0.8 while a
    paragraph of filler collapses toward zero.
    """
    found: list[str] = []
    for label, pattern in _SLOP_PATTERNS:
        if pattern.search(text):
            found.append(label)
    score = max(0.0, 1.0 - 0.2 * len(found))
    return SlopResult(found=tuple(found), score=score)
