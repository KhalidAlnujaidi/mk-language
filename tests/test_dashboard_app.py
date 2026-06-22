"""The dashboard UI shell (vision §9 #5) — thin rich renderer over the summary.

The aggregation is tested separately; here we only prove the UI builds a table
from a summary and can read a JSONL sink (it "launches" without a server).
"""

from __future__ import annotations

from pathlib import Path

from kernel.contracts import EventRecord
from kernel.metrics import MetricsSink
from products.dashboard.aggregate import summarize
from products.dashboard.app import build_summary, render


def test_render_returns_a_table_with_one_row_per_tier():
    from rich.table import Table

    summary = summarize(
        [
            EventRecord("a", "tag", "model:local", latency_ms=1.0),
            EventRecord("b", "redact", "deterministic", latency_ms=2.0),
        ]
    )
    table = render(summary)
    assert isinstance(table, Table)
    assert table.row_count == 2  # one row per tier


def test_build_summary_reads_the_jsonl_sink(tmp_path: Path):
    sink = MetricsSink(tmp_path / "events.jsonl")
    sink.record(EventRecord("a", "tag", "model:local"))
    summary = build_summary(tmp_path / "events.jsonl")
    assert summary.total_events == 1
