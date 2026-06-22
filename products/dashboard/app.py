"""Observability dashboard UI shell (vision §9 #5).

A thin rich renderer over the pure ``aggregate.summarize`` — reuses rich for the
table (Rule Zero, no hand-rolled renderer). All the logic lives in
``aggregate``; this module only reads the JSONL sink and draws.

Run:  uv run python -m products.dashboard.app [path-to-events.jsonl]
"""

from __future__ import annotations

import sys
from pathlib import Path

from kernel.metrics import MetricsSink
from rich.console import Console
from rich.table import Table

from products.dashboard.aggregate import Summary, summarize


def _fmt(value: float | int | None) -> str:
    """Render a metric, honestly marking unknowns rather than faking a 0."""
    return (
        "—"
        if value is None
        else (f"{value:.1f}" if isinstance(value, float) else str(value))
    )


def render(summary: Summary) -> Table:
    """Build a rich table (one row per tier) from a summary."""
    caption = (
        f"{summary.total_events} events · "
        f"{summary.correction_count} corrections "
        f"({summary.correction_rate:.0%})"
    )
    table = Table(title="kinox observability", caption=caption)
    table.add_column("tier")
    table.add_column("count", justify="right")
    table.add_column("avg latency (ms)", justify="right")
    table.add_column("tokens out", justify="right")
    table.add_column("exact?")
    for r in summary.per_tier:
        table.add_row(
            r.tier,
            str(r.count),
            _fmt(r.avg_latency_ms),
            _fmt(r.total_tokens_out),
            "yes" if r.tokens_exact else "est",
        )
    return table


def build_summary(path: Path) -> Summary:
    """Read the EventRecord JSONL at *path* and summarise it."""
    return summarize(MetricsSink(path).read_all())


def main(argv: list[str] | None = None) -> None:  # pragma: no cover - thin shell
    args = sys.argv[1:] if argv is None else argv
    path = Path(args[0]) if args else Path.home() / ".kinox" / "broker-events.jsonl"
    Console().print(render(build_summary(path)))


if __name__ == "__main__":  # pragma: no cover
    main()
