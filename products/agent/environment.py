"""Compile the agent session preamble — scope-aware.

There are two scopes, and each is told only what it should know:

* **Project scope** receives the **operating axioms** alone (``alignment/AXIOMS.md``)
  — the rules it must follow, with nothing about the framework that runs it. A
  project is not aware of the framework scope; it only follows the axioms
  pre-injected into it.
* **Framework scope** (working *on* kinox) receives the axioms **plus** the
  framework internals (``alignment/PREAMBLE.md``) — kinox's own structure.

Each fact appears exactly once: the axioms live in one file, the framework
internals in another, and the framework preamble is their concatenation. Deeper
detail lives in the source documents (CONSTITUTION.md, vision.md, BRAIN.md) and
is read on demand.

Results are cached after first computation (the source files do not change
mid-session). A missing file is skipped silently (fail-soft).
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

#: Universal governing axioms — injected into EVERY scope.
_AXIOMS_FILE = "alignment/AXIOMS.md"

#: Framework internals — injected only in framework scope, after the axioms.
_FRAMEWORK_FILE = "alignment/PREAMBLE.md"

#: Maximum preamble length in characters — a safety net, not the primary size
#: control (the files are authored lean). Only triggers if someone bloats them.
_MAX_PREAMBLE = 8_000


def _read(root: str | Path, rel: str) -> str:
    """Read ``root/rel`` stripped, or ``""`` if missing/unreadable (fail-soft)."""
    try:
        return (Path(root) / rel).read_text(encoding="utf-8").strip()
    except (OSError, UnicodeDecodeError):
        return ""


def _capped(body: str) -> str:
    """Truncate *body* to the safety-net length, with a marker."""
    if len(body) > _MAX_PREAMBLE:
        return body[:_MAX_PREAMBLE].rstrip() + "\n\n…(truncated)"
    return body


@lru_cache(maxsize=8)
def build_axioms(root: str | Path) -> str:
    """The operating axioms — the preamble for a **project** scope.

    Returns the contents of ``alignment/AXIOMS.md`` (the rules every agent
    follows), or ``""`` if absent. This is *all* a project session is told about
    how it is governed — never the framework's structure. Cached per *root*.
    """
    return _capped(_read(root, _AXIOMS_FILE))


@lru_cache(maxsize=8)
def build_preamble(root: str | Path) -> str:
    """The **framework**-scope preamble: axioms + framework internals.

    Concatenates ``alignment/AXIOMS.md`` and ``alignment/PREAMBLE.md`` so an agent
    working *on* kinox knows both the rules and kinox's own structure. If only one
    file is present, returns just that one; ``""`` if neither. Cached per *root*.
    """
    axioms = _read(root, _AXIOMS_FILE)
    framework = _read(root, _FRAMEWORK_FILE)
    parts = [p for p in (axioms, framework) if p]
    if not parts:
        return ""
    return _capped("\n\n---\n\n".join(parts))


def session_preamble(root: str | Path, *, framework: bool) -> str:
    """The preamble for a session: framework scope gets internals, project doesn't.

    *framework* True → :func:`build_preamble` (axioms + internals); False →
    :func:`build_axioms` (axioms only). This is the single switch that keeps a
    project unaware of the framework scope.
    """
    return build_preamble(root) if framework else build_axioms(root)


def clear_cache() -> None:
    """Clear the preamble caches (tests / long-running daemons picking up edits)."""
    build_axioms.cache_clear()
    build_preamble.cache_clear()
