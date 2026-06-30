# swarm-drafted (node=gemma-agent-6, model=Nemotron-14B); curated locally
# Behavioral: the sink is append-only and round-trips EventRecords in order;
# a fresh sink is empty. Reads reconstruct by value (frozen dataclass), so we
# compare with == not identity.
import tempfile
from pathlib import Path

from kernel.contracts import EventRecord
from kernel.metrics import MetricsSink


def test_metrics_sink_roundtrip_and_order():
    path = Path(tempfile.mkdtemp()) / "metrics.jsonl"
    sink = MetricsSink(path)

    e1 = EventRecord(task_id="t-1", kind="redact", tier="deterministic")
    e2 = EventRecord(task_id="t-2", kind="tag", tier="model:local")
    sink.record(e1)
    sink.record(e2)

    recorded = sink.read_all()
    assert recorded == [e1, e2]  # both, in append order
    assert sink.last() == e2  # most recent


def test_fresh_sink_is_empty():
    path = Path(tempfile.mkdtemp()) / "empty.jsonl"
    sink = MetricsSink(path)
    assert sink.read_all() == []
    assert sink.last() is None
