"""Free-label correction heuristic (thesis #3).

The user's immediate next-turn correction is a free quality label.
This module is a pure, stdlib-only heuristic detector; model-scored later.
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Public constants
# ---------------------------------------------------------------------------

CORRECTION_CUES: frozenset[str] = frozenset(
    {"no", "actually", "i meant", "not", "wrong", "nope", "i said"}
)

MAX_CORRECTION_WORDS: int = 12

# Punctuation characters that may immediately follow a cue at a word boundary.
_BOUNDARY_CHARS: tuple[str, ...] = (" ", ",", ".", "!", "?", ";")


def looks_like_correction(prev_prompt: str, next_prompt: str) -> bool:
    """Return True iff ``next_prompt`` looks like a correction of ``prev_prompt``.

    Conditions (all must hold):
    - ``prev_prompt`` is non-empty.
    - ``next_prompt`` (stripped, lowercased) starts with one of
      ``CORRECTION_CUES`` on a word/punctuation boundary (so "nope" matches
      but "nominal" does not).
    - ``next_prompt`` has at most ``MAX_CORRECTION_WORDS`` words.
    """
    if not prev_prompt:
        return False

    normalised = next_prompt.strip().lower()

    if len(normalised.split()) > MAX_CORRECTION_WORDS:
        return False

    for cue in CORRECTION_CUES:
        if normalised == cue:
            return True
        for boundary in _BOUNDARY_CHARS:
            if normalised.startswith(cue + boundary):
                return True

    return False
