"""Compile the kinox project environment + axioms into an agent system preamble.

A single canonical file (``alignment/PREAMBLE.md``) is the sole source.  It is a
lean, hand-curated summary in which each fact appears exactly once — no
duplication, no 5-file concatenation, no hard truncation.

The full source documents (``CONSTITUTION.md``, ``vision.md``, ``BRAIN.md``,
``README.md``) remain as human reference and can be read on demand via tools.
The preamble is the *starting context*, not a substitute for those files.

The result is cached after first computation (the source file does not change
mid-session) to avoid re-reading on every turn.  A missing file is skipped
silently (fail-soft — a minimal checkout still works).
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

#: The single canonical preamble source.  Each fact appears exactly once here;
#: the full detail lives in CONSTITUTION.md / vision.md / BRAIN.md / README.md
#: and can be read on demand.
_PREAMBLE_FILE = "alignment/PREAMBLE.md"

#: Maximum preamble length in characters — a safety net, not the primary size
#: control (the file itself is authored to ~3k).  Only triggers if someone
#: bloats the file.
_MAX_PREAMBLE = 8_000


@lru_cache(maxsize=8)
def build_preamble(root: str | Path) -> str:
    """Read the canonical preamble file and return it as a system-prompt string.

    Returns a markdown block suitable for prepending to a system prompt.
    A missing file returns ``""`` (fail-soft).  The result is cached per *root*
    so repeated calls in the same session are free.

    Parameters
    ----------
    root:
        The kinox repository root (the directory that *contains*
        ``alignment/``).

    Returns
    -------
    str
        The preamble text, or ``""`` when the file was not found.
    """
    path = Path(root) / _PREAMBLE_FILE
    try:
        body = path.read_text(encoding="utf-8").strip()
    except (OSError, UnicodeDecodeError):
        return ""
    if not body:
        return ""
    if len(body) > _MAX_PREAMBLE:
        body = body[:_MAX_PREAMBLE].rstrip() + "\n\n…(truncated)"
    return body


def clear_cache() -> None:
    """Clear the preamble cache.

    Useful in tests when the filesystem is mutated between assertions, or when
    a long-running daemon picks up new project files.
    """
    build_preamble.cache_clear()
