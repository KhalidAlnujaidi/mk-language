"""Pure aggregation for the observability dashboard (vision §9 #5).

Turns a list of ``EventRecord`` into a ``Summary``: total events, correction
count + rate, and a per-tier rollup (count, average latency, total output
tokens, and an honest ``tokens_exact`` flag that is only ``True`` when *every*
event in the tier reported exact counts — a single cloud estimate makes the
whole tier inexact). All rendering lives in the thin UI shell; this stays pure
and fully unit-tested.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass

from kernel.contracts import EventRecord


@dataclass(frozen=True)
class TierRollup:
    """Aggregated stats for one tier string."""

    tier: str
    count: int
    avg_latency_ms: float | None
    total_tokens_out: int | None
    tokens_exact: bool


@dataclass(frozen=True)
class Summary:
    """Top-level dashboard summary over a batch of events."""

    total_events: int
    correction_count: int
    correction_rate: float
    per_tier: list[TierRollup]


def summarize(events: list[EventRecord]) -> Summary:
    """Roll *events* up into a ``Summary`` (pure; safe on an empty list)."""
    total = len(events)
    corrections = sum(1 for e in events if e.correction_of is not None)
    rate = corrections / total if total else 0.0

    by_tier: dict[str, list[EventRecord]] = defaultdict(list)
    for e in events:
        by_tier[e.tier].append(e)

    rollups: list[TierRollup] = []
    for tier in sorted(by_tier):
        evs = by_tier[tier]
        latencies = [e.latency_ms for e in evs if e.latency_ms is not None]
        avg_latency = sum(latencies) / len(latencies) if latencies else None
        token_counts = [e.tokens_out for e in evs if e.tokens_out is not None]
        total_out = sum(token_counts) if token_counts else None
        # Honest: exact only when every event in the tier is exact.
        exact = all(e.tokens_exact for e in evs)
        rollups.append(
            TierRollup(
                tier=tier,
                count=len(evs),
                avg_latency_ms=avg_latency,
                total_tokens_out=total_out,
                tokens_exact=exact,
            )
        )

    return Summary(
        total_events=total,
        correction_count=corrections,
        correction_rate=rate,
        per_tier=rollups,
    )
