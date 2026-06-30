"""Next-turn feedback loop (vision §9 #1, thesis #3).

When the next prompt corrects the prior, mark the prior task corrected in the
metrics JSONL — the free quality label. Reuses kernel.corrections for detection.
"""

from __future__ import annotations

from pathlib import Path

from kernel.metrics import MetricsSink
from products.feedback.loop import record_correction_if_any


def test_correction_turn_marks_prior_task(tmp_path: Path):
    sink = MetricsSink(tmp_path / "events.jsonl")
    marked = record_correction_if_any(
        sink,
        prior_task_id="t-1",
        prior_prompt="add a button",
        next_prompt="no, make it red",
        task_id="t-2",
    )
    assert marked is True
    events = sink.read_all()
    assert any(e.correction_of == "t-1" for e in events)


def test_non_correction_records_nothing(tmp_path: Path):
    sink = MetricsSink(tmp_path / "events.jsonl")
    marked = record_correction_if_any(
        sink,
        prior_task_id="t-1",
        prior_prompt="add a button",
        next_prompt="now add a footer too",
        task_id="t-2",
    )
    assert marked is False
    assert sink.read_all() == []
