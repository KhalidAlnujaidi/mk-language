"""Pure aggregation for the observability dashboard (vision §9 #5).

Rolls EventRecords up into per-tier counts/latency/tokens + correction rate.
Token-exactness is honest: a tier is only 'exact' if every event in it is.
"""

from __future__ import annotations

from kernel.contracts import EventRecord
from products.dashboard.aggregate import summarize


def test_summarize_counts_and_correction_rate():
    events = [
        EventRecord(
            "t1",
            "tag",
            "model:local",
            tokens_out=10,
            latency_ms=100.0,
            tokens_exact=True,
        ),
        EventRecord(
            "t2",
            "tag",
            "model:local",
            tokens_out=20,
            latency_ms=200.0,
            tokens_exact=True,
        ),
        EventRecord("t3", "correction", "deterministic").as_correction_of("t1"),
        EventRecord("t4", "redact", "deterministic", latency_ms=5.0),
    ]
    s = summarize(events)
    assert s.total_events == 4
    assert s.correction_count == 1
    assert s.correction_rate == 0.25


def test_per_tier_rollup_latency_and_tokens():
    events = [
        EventRecord(
            "t1",
            "tag",
            "model:local",
            tokens_out=10,
            latency_ms=100.0,
            tokens_exact=True,
        ),
        EventRecord(
            "t2",
            "tag",
            "model:local",
            tokens_out=20,
            latency_ms=200.0,
            tokens_exact=True,
        ),
    ]
    s = summarize(events)
    local = next(r for r in s.per_tier if r.tier == "model:local")
    assert local.count == 2
    assert local.avg_latency_ms == 150.0
    assert local.total_tokens_out == 30
    assert local.tokens_exact is True


def test_tokens_exact_is_false_if_any_estimate():
    events = [
        EventRecord("a", "x", "model:cloud", tokens_out=5, tokens_exact=False),
        EventRecord("b", "x", "model:cloud", tokens_out=5, tokens_exact=True),
    ]
    s = summarize(events)
    cloud = next(r for r in s.per_tier if r.tier == "model:cloud")
    assert cloud.tokens_exact is False  # honest: not all exact


def test_empty_events_are_safe():
    s = summarize([])
    assert s.total_events == 0
    assert s.correction_rate == 0.0
    assert s.per_tier == []
