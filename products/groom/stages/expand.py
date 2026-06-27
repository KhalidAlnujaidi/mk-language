"""Stage: expand — filesystem path mention resolution.

Thesis #1: ground truth beats the model — pure fs lookup, no model call.
Thesis #2: fail-direction is SOFT (optimizer); degrades to input-unchanged with
empty notes on any error.

Two kinds of mention get an existence note: an explicit ``@path`` mention, and a
bare *relative/absolute path* token (``./README.md``, ``../x``, ``/etc/hosts``) —
the latter so a natural "read the file at ./README.md" is grounded too, not only
the ``@`` shorthand. Existence is checked relative to *cwd* (the session scope)
when given, so the note reflects the scope, not the process's working directory.
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

# Match a BARE path token: ``./x``, ``../x``, or ``/x`` at a word boundary. Kept
# deliberately explicit (must start with ./, ../, or /) so ordinary words and
# email/host tokens are never mistaken for paths. A trailing sentence period is
# trimmed off the note ("read ./README.md." → "./README.md").
_BARE_PATH: re.Pattern[str] = re.compile(
    r"(?:^|(?<=\s))(\.{1,2}/[^\s,;\"']+|/[^\s,;\"']+)"
)


@dataclass(frozen=True)
class ExpandResult:
    """The result of an expand pass."""

    text: str
    notes: tuple[str, ...]


def expand(text: str, *, cwd: Path | None = None) -> ExpandResult:
    """Find path mentions (``@path`` and bare ``./path``) and note their existence.

    Existence is resolved relative to *cwd* when given (the session scope), else
    the process working directory. On any error, returns the input unchanged with
    empty notes (SOFT).
    """
    base = Path(cwd) if cwd is not None else Path()
    try:
        notes: list[str] = []
        seen: set[str] = set()

        def _note(token: str, *, prefix: str) -> None:
            tok = token.rstrip(".")  # trim a trailing sentence period
            if not tok or tok in seen:
                return
            seen.add(tok)
            target = Path(tok) if tok.startswith("/") else base / tok
            status = "exists" if target.exists() else "missing"
            notes.append(f"{prefix}{tok} → {status}")

        for match in _PATH_MENTION.finditer(text):
            _note(match.group(1), prefix="@")
        for match in _BARE_PATH.finditer(text):
            _note(match.group(1), prefix="")
        return ExpandResult(text=text, notes=tuple(notes))
    except Exception:
        return ExpandResult(text=text, notes=())
