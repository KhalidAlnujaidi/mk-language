"""Stage: tag — keyword-based tagging with honest router wiring.

Thesis #1: tag is the ONE fuzzy step in the groom pipeline.
Thesis #2: fail-direction is SOFT — if the router returns nothing, fall back to
           deterministic tier and keyword tags (never block).

For M0 we do NOT call a model: the tag set is produced deterministically from
keyword triggers. What IS real is the router call — the EventRecord tier string
reflects the actual routed tier so the boundary record is honest.
"""

from __future__ import annotations

from dataclasses import dataclass

from kernel.contracts import FailDirection, Task, TaskKind, Tier
from kernel.manifest import Manifest
from kernel.router import route

FAIL_DIRECTION: FailDirection = FailDirection.SOFT

# Budget cap for the fuzzy TAG task (milliseconds).
TAG_BUDGET_MS: int = 200

# Keyword trigger map → tag label.
# Each trigger word is a lowercase substring that implies the tag.
_TRIGGERS: tuple[tuple[str, str], ...] = (
    ("fix", "bug"),
    ("error", "bug"),
    ("bug", "bug"),
    ("add", "feature"),
    ("implement", "feature"),
    ("feature", "feature"),
    ("refactor", "refactor"),
    ("restructure", "refactor"),
    ("cleanup", "refactor"),
    ("test", "test"),
    ("spec", "test"),
    ("doc", "docs"),
    ("readme", "docs"),
    ("why", "question"),
    ("how", "question"),
    ("?", "question"),
)

_VALID_TAGS: frozenset[str] = frozenset(
    {"bug", "feature", "refactor", "test", "docs", "question"}
)


def _keyword_tags(text: str) -> tuple[str, ...]:
    """Deterministic keyword scan — emits any tag whose trigger appears in *text*.

    Preserves insertion-discovery order and deduplicates.

    Asserts every produced tag is in ``_VALID_TAGS`` so that the trigger map
    and the valid-tag set cannot silently drift.
    """
    lowered = text.lower()
    seen: set[str] = set()
    tags: list[str] = []
    for trigger, label in _TRIGGERS:
        if trigger in lowered and label not in seen:
            assert label in _VALID_TAGS, (
                f"Trigger {trigger!r} maps to {label!r} which is not in _VALID_TAGS"
            )
            seen.add(label)
            tags.append(label)
    return tuple(tags)


@dataclass(frozen=True)
class TagResult:
    """The result of a tag pass."""

    tags: tuple[str, ...]
    tier: Tier


def tag(text: str, manifest: Manifest) -> TagResult:
    """Tag *text* with keyword triggers and route for real (M0: no model call).

    Builds a ``Task(kind=TaskKind.TAG, budget_ms=TAG_BUDGET_MS)`` and asks the
    router which tier to use. Returns keyword-derived tags (deterministic
    fallback, SOFT) and the routed ``Tier`` so the boundary record is honest.

    If ``route`` returns ``None`` (no capable tier), falls back to
    ``Tier.deterministic()``.
    """
    task = Task(kind=TaskKind.TAG, budget_ms=TAG_BUDGET_MS)
    routed: Tier | None = route(task, manifest)
    tier: Tier = routed if routed is not None else Tier.deterministic()
    return TagResult(tags=_keyword_tags(text), tier=tier)
