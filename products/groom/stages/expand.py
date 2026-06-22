"""Stage: expand — filesystem path @-mention resolution.

Thesis #1: ground truth beats the model — pure fs lookup, no model call.
Thesis #2: fail-direction is SOFT (optimizer); degrades to input-unchanged with
empty notes on any error.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from kernel.contracts import FailDirection

FAIL_DIRECTION: FailDirection = FailDirection.SOFT

# Match @<token> where token looks like a path: contains / or . (but not email @word).
# A path token starts with / (absolute) or contains a / or . separator.
# The @ must appear at start-of-string or be preceded by whitespace so that
# email addresses (user@example.com) do NOT match.
_PATH_MENTION: re.Pattern[str] = re.compile(
    r"(?:^|(?<=\s))@((?:/[^\s,;\"']*)|(?:[^\s@,;\"']*[/.][^\s,;\"']*))"
)


@dataclass(frozen=True)
class ExpandResult:
    """The result of an expand pass."""

    text: str
    notes: tuple[str, ...]


def expand(text: str) -> ExpandResult:
    """Find @-mentions of filesystem paths and append existence notes.

    On any error, returns the input text unchanged with empty notes (SOFT).
    """
    try:
        notes: list[str] = []
        for match in _PATH_MENTION.finditer(text):
            token = match.group(1)
            path = Path(token)
            status = "exists" if path.exists() else "missing"
            notes.append(f"@{token} → {status}")
        return ExpandResult(text=text, notes=tuple(notes))
    except Exception:
        return ExpandResult(text=text, notes=())
