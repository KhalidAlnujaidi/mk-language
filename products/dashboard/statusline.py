"""Live status-line chips over the metrics JSONL (CodeWhale Tier-2 + vision §9 #5).

CodeWhale's status line is an ordered array of pure-render *chips* (model, cost,
tokens, …) the user can reorder. kinox already aggregates ``EventRecord`` rows
(``products/dashboard/aggregate.py``); this renders the same stream as a compact
one-liner — the fast path of the observability dashboard (vision §9 #5), with no
server and no extra state.

Cost is the cost thesis (#1) made visible. Local tiers are free; cloud tiers are
*estimates* — honest observability (vision §4.6: never claim a cloud count or cost
is exact), so an estimated cost is marked with a ``~`` prefix and ``cost_exact``
is ``False``. Everything here is a pure function of the event list (thesis #1) — no
I/O, no model — so a chip can never lie about what was measured.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass

from kernel.contracts import EventRecord

# $ per 1,000,000 tokens, (input, output), keyed by tier *location*. Local serving
# is free; the cloud figure is a deliberately rough DEFAULT ESTIMATE (override per
# deployment) — cloud token counts are already inexact, so any cloud cost is an
# estimate by construction.
_PRICING: dict[str, tuple[float, float]] = {
    "local": (0.0, 0.0),
    "cloud": (0.50, 1.50),
}


def _tier_where(tier: str) -> str | None:
    """The location segment of a tier string (``model:cloud:glm`` → ``"cloud"``);
    ``None`` for the deterministic (no-model) tier."""
    parts = tier.split(":")
    if len(parts) >= 2 and parts[0] == "model":
        return parts[1]
    return None


@dataclass(frozen=True)
class StatusModel:
    """The compact live state a status line renders, derived purely from events."""

    events: int
    tokens_in: int
    tokens_out: int
    cost_usd: float
    cost_exact: bool  # False once any cloud (estimated) token contributes
    top_tier: str | None  # most-frequent tier string, or None when empty
    correction_rate: float


def build(events: list[EventRecord]) -> StatusModel:
    """Fold *events* into a :class:`StatusModel`. Pure and deterministic."""
    tokens_in = sum(e.tokens_in or 0 for e in events)
    tokens_out = sum(e.tokens_out or 0 for e in events)

    cost = 0.0
    cost_exact = True
    for e in events:
        where = _tier_where(e.tier)
        rates = _PRICING.get(where) if where is not None else None
        if rates is None:
            continue
        in_rate, out_rate = rates
        cost += (e.tokens_in or 0) / 1e6 * in_rate
        cost += (e.tokens_out or 0) / 1e6 * out_rate
        # Any cloud token makes the cost an estimate (honest observability).
        if where == "cloud" and ((e.tokens_in or 0) or (e.tokens_out or 0)):
            cost_exact = False

    corrections = sum(1 for e in events if e.correction_of is not None)
    rate = corrections / len(events) if events else 0.0

    top_tier: str | None = None
    if events:
        top_tier = Counter(e.tier for e in events).most_common(1)[0][0]

    return StatusModel(
        events=len(events),
        tokens_in=tokens_in,
        tokens_out=tokens_out,
        cost_usd=cost,
        cost_exact=cost_exact,
        top_tier=top_tier,
        correction_rate=rate,
    )


def _short_tier(tier: str | None) -> str:
    """Compact a tier string for the chip (``model:cloud:glm`` → ``cloud:glm``)."""
    if tier is None:
        return "—"
    return tier[len("model:"):] if tier.startswith("model:") else tier


# Chip renderers — each is a pure ``StatusModel -> str``. Add one here and name it
# in *chips* to surface it; reorder freely (CodeWhale's reorderable chip array).
_CHIPS: dict[str, Callable[[StatusModel], str]] = {
    "tier": lambda m: _short_tier(m.top_tier),
    "events": lambda m: f"{m.events} ev",
    "tokens": lambda m: f"{m.tokens_in}→{m.tokens_out} tok",
    "cost": lambda m: ("~" if not m.cost_exact else "") + f"${m.cost_usd:.4f}",
    "corrections": lambda m: f"{m.correction_rate:.0%} corr",
}

#: Default chip order, left to right.
DEFAULT_CHIPS: tuple[str, ...] = ("tier", "events", "tokens", "cost", "corrections")


def render(
    events: list[EventRecord],
    *,
    chips: tuple[str, ...] = DEFAULT_CHIPS,
    sep: str = " · ",
) -> str:
    """Render a one-line status line over *events*.

    *chips* is an ordered tuple of chip names (declarative + reorderable, like
    CodeWhale's status_items). An unknown chip name is skipped (fail-SOFT — a
    typo in a config drops the chip, it never crashes the line)."""
    model = build(events)
    parts = [_CHIPS[name](model) for name in chips if name in _CHIPS]
    return sep.join(parts)
