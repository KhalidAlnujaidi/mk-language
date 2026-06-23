"""Stage: tag — keyword-based tagging with honest router wiring.

Thesis #1: tag is the ONE fuzzy step in the groom pipeline.
Thesis #2: fail-direction is SOFT — if the router returns nothing, fall back to
           deterministic tier and keyword tags (never block).

For M0 we do NOT call a model: the tag set is produced deterministically from
keyword triggers. What IS real is the router call — the EventRecord tier string
reflects the actual routed tier so the boundary record is honest.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from kernel.contracts import FailDirection, Task, TaskKind, Tier
from kernel.manifest import Manifest
from kernel.router import route

FAIL_DIRECTION: FailDirection = FailDirection.SOFT

#: A model-backed tagger: given the routed model tier and the text, return tags
#: (or ``None`` to decline — the caller then falls soft to keyword tags).
ModelTag = Callable[[Tier, str], "tuple[str, ...] | None"]

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

VALID_TAGS: frozenset[str] = frozenset(
    {"bug", "feature", "refactor", "test", "docs", "question"}
)


def _keyword_tags(text: str) -> tuple[str, ...]:
    """Deterministic keyword scan — emits any tag whose trigger appears in *text*.

    Preserves insertion-discovery order and deduplicates.

    Asserts every produced tag is in ``VALID_TAGS`` so that the trigger map
    and the valid-tag set cannot silently drift.
    """
    lowered = text.lower()
    seen: set[str] = set()
    tags: list[str] = []
    for trigger, label in _TRIGGERS:
        if trigger in lowered and label not in seen:
            assert label in VALID_TAGS, (
                f"Trigger {trigger!r} maps to {label!r} which is not in VALID_TAGS"
            )
            seen.add(label)
            tags.append(label)
    return tuple(tags)


@dataclass(frozen=True)
class TagResult:
    """The result of a tag pass."""

    tags: tuple[str, ...]
    tier: Tier


def tag(
    text: str, manifest: Manifest, *, model_tag: ModelTag | None = None
) -> TagResult:
    """Tag *text*: route for real, optionally offloading to a local model.

    Builds a ``Task(kind=TaskKind.TAG, budget_ms=TAG_BUDGET_MS)`` and asks the
    router which tier to use. When *model_tag* is supplied AND the routed tier is
    a model, the fuzzy tag is offloaded to that model; a non-empty result is
    trusted. Otherwise — no tagger, a deterministic tier, or a model that
    declines (``None``) — we fall soft to deterministic keyword tags (SOFT
    fail-direction). The returned ``Tier`` is the routed one, so the boundary
    record stays honest.
    """
    task = Task(kind=TaskKind.TAG, budget_ms=TAG_BUDGET_MS)
    routed: Tier | None = route(task, manifest)
    tier: Tier = routed if routed is not None else Tier.deterministic()

    if model_tag is not None and tier.is_model:
        model_tags = model_tag(tier, text)
        if model_tags:  # non-empty → trust the model
            return TagResult(tags=tuple(model_tags), tier=tier)

    return TagResult(tags=_keyword_tags(text), tier=tier)
