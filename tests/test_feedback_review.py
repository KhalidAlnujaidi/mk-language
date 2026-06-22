"""Cheap-reviewer stub over correction events (vision §9 #1).

Reads correction EventRecords from the sink and aggregates them into a
"what to review" list — no model call required for the stub.
"""

from __future__ import annotations

from pathlib import Path

from kernel.contracts import EventRecord
from kernel.metrics import MetricsSink
from products.feedback.review import review


def test_review_aggregates_corrections_by_prior_task(tmp_path: Path):
    sink = MetricsSink(tmp_path / "events.jsonl")
    sink.record(
        EventRecord("t-2", "correction", "deterministic").as_correction_of("t-1")
    )
    sink.record(
        EventRecord("t-3", "correction", "deterministic").as_correction_of("t-1")
    )
    sink.record(EventRecord("t-9", "tag", "model:local"))  # non-correction → ignored

    items = review(sink)
    assert len(items) == 1
    item = items[0]
    assert item.prior_task_id == "t-1"
    assert item.times_corrected == 2
    assert set(item.correcting_task_ids) == {"t-2", "t-3"}


def test_review_empty_when_no_corrections(tmp_path: Path):
    sink = MetricsSink(tmp_path / "events.jsonl")
    sink.record(EventRecord("t-1", "tag", "model:local"))
    assert review(sink) == []
