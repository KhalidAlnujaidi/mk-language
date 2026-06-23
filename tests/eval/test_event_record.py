# swarm-drafted (node=gemma-agent-5, model=Nemotron-14B); curated locally
# Behavioral: EventRecord defaults are honest (correction_of null, counts not
# claimed exact) and as_correction_of is a non-mutating copy (thesis #3 / HT#4).
from kernel.contracts import EventRecord


def test_event_record_honest_defaults():
    event = EventRecord(task_id="t-1", kind="redact", tier="deterministic")
    assert event.correction_of is None  # null, not a fabricated value
    assert event.tokens_exact is False  # never claim counts are exact by default


def test_as_correction_of_is_nonmutating_copy():
    full = EventRecord(
        task_id="source",
        kind="tag",
        tier="model:local",
        tokens_in=42,
        tokens_out=17,
        latency_ms=500.0,
        tokens_exact=True,
    )
    copied = full.as_correction_of("prev-task")

    assert copied.correction_of == "prev-task"
    assert full.correction_of is None  # frozen: original untouched
    for attr in (
        "task_id",
        "kind",
        "tier",
        "tokens_in",
        "tokens_out",
        "latency_ms",
        "tokens_exact",
    ):
        assert getattr(copied, attr) == getattr(full, attr)
