"""Tests for the append-only EventRecord sink (kernel/metrics.py)."""

from __future__ import annotations

from kernel.contracts import EventRecord
from kernel.metrics import MetricsSink


def test_record_then_read_roundtrips_all_fields(tmp_path: object) -> None:
    sink = MetricsSink(tmp_path / "events.jsonl")  # type: ignore[operator]
    ev = EventRecord(task_id="t1", kind="tag", tier="model:local",
                     tokens_in=10, tokens_out=3, tokens_exact=True, latency_ms=12.5)
    sink.record(ev)
    assert sink.read_all() == [ev]


def test_record_is_append_only(tmp_path: object) -> None:
    sink = MetricsSink(tmp_path / "events.jsonl")  # type: ignore[operator]
    a = EventRecord(task_id="a", kind="redact", tier="deterministic")
    b = EventRecord(task_id="b", kind="tag", tier="model:cloud")
    sink.record(a)
    sink.record(b)
    assert [e.task_id for e in sink.read_all()] == ["a", "b"]
    assert (tmp_path / "events.jsonl").read_text().count("\n") == 2  # type: ignore[union-attr]


def test_correction_of_survives_roundtrip(tmp_path: object) -> None:
    sink = MetricsSink(tmp_path / "e.jsonl")  # type: ignore[operator]
    ev = (
        EventRecord(task_id="t2", kind="tag", tier="model:local")
        .as_correction_of("t1")
    )
    sink.record(ev)
    assert sink.read_all()[0].correction_of == "t1"


def test_read_all_empty_when_missing(tmp_path: object) -> None:
    assert MetricsSink(tmp_path / "nope.jsonl").read_all() == []  # type: ignore[operator]


def test_last_returns_most_recent_or_none(tmp_path: object) -> None:
    sink = MetricsSink(tmp_path / "e.jsonl")  # type: ignore[operator]
    assert sink.last() is None
    sink.record(EventRecord(task_id="x", kind="tag", tier="t"))
    sink.record(EventRecord(task_id="y", kind="tag", tier="t"))
    assert sink.last() is not None
    assert sink.last().task_id == "y"  # type: ignore[union-attr]


def test_creates_parent_dirs(tmp_path: object) -> None:
    sink = MetricsSink(tmp_path / "deep" / "nested" / "e.jsonl")  # type: ignore[operator]
    sink.record(EventRecord(task_id="x", kind="tag", tier="t"))
    assert (tmp_path / "deep" / "nested" / "e.jsonl").exists()  # type: ignore[union-attr]
