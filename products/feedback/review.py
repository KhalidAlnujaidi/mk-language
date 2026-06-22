"""Cheap-reviewer stub over correction events (vision §9 #1).

Reads the metrics sink, finds the EventRecords that mark a prior task corrected
(``correction_of`` set), and groups them per prior task into ``ReviewItem``s —
a structured "what to review" list. This is the deterministic stub; a later
version routes the most-corrected tasks to a cheap local reviewer model.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass

from kernel.metrics import MetricsSink


@dataclass(frozen=True)
class ReviewItem:
    """One prior task that drew one or more next-turn corrections."""

    prior_task_id: str
    times_corrected: int
    correcting_task_ids: tuple[str, ...]


def review(sink: MetricsSink) -> list[ReviewItem]:
    """Aggregate correction events into per-prior-task review items.

    Ordered most-corrected first, so the worst offenders surface at the top.
    """
    by_prior: dict[str, list[str]] = defaultdict(list)
    for event in sink.read_all():
        if event.correction_of is not None:
            by_prior[event.correction_of].append(event.task_id)

    items = [
        ReviewItem(
            prior_task_id=prior,
            times_corrected=len(correctors),
            correcting_task_ids=tuple(correctors),
        )
        for prior, correctors in by_prior.items()
    ]
    items.sort(key=lambda i: i.times_corrected, reverse=True)
    return items
