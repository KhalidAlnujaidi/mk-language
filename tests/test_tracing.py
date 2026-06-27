"""The pluggable kernel tracing seam (vision §7).

Proves the seam works with NO OpenTelemetry installed: a no-op by default (so
every ``span(...)`` across the codebase is free), delegating to a tracer once one
is installed, and fail-soft if that tracer misbehaves — instrumentation can never
break the code it wraps.
"""

from __future__ import annotations

from collections.abc import Mapping
from contextlib import contextmanager

import pytest
from kernel import tracing


@pytest.fixture(autouse=True)
def _reset_tracer():
    """Each test starts and ends with the default no-op tracer (global state)."""
    tracing.set_tracer(None)
    yield
    tracing.set_tracer(None)


class _RecordingSpan:
    def __init__(self) -> None:
        self.attributes: dict[str, object] = {}

    def set_attribute(self, key: str, value: object) -> None:
        self.attributes[key] = value


class _RecordingTracer:
    """Records the sequence of span names + attributes (no OTel needed)."""

    def __init__(self) -> None:
        self.spans: list[tuple[str, dict[str, object]]] = []

    @contextmanager
    def span(self, name: str, attributes: Mapping[str, object] | None = None):
        s = _RecordingSpan()
        self.spans.append((name, dict(attributes or {})))
        yield s


def test_span_is_a_noop_by_default() -> None:
    # No tracer installed → span() still works and yields a usable (no-op) span.
    assert not tracing.tracing_enabled()
    with tracing.span("anything", {"k": "v"}) as s:
        s.set_attribute("more", 1)  # must not raise
    assert not tracing.tracing_enabled()


def test_set_tracer_delegates_and_records() -> None:
    rec = _RecordingTracer()
    tracing.set_tracer(rec)
    assert tracing.tracing_enabled()
    with (
        tracing.span("groom", {"kinox.task_id": "abc"}),
        tracing.span("broker.execute"),
    ):
        pass
    assert [n for n, _ in rec.spans] == ["groom", "broker.execute"]
    assert rec.spans[0][1] == {"kinox.task_id": "abc"}


def test_set_tracer_none_restores_noop() -> None:
    tracing.set_tracer(_RecordingTracer())
    assert tracing.tracing_enabled()
    tracing.set_tracer(None)
    assert not tracing.tracing_enabled()


def test_span_is_failsoft_when_tracer_raises_on_open() -> None:
    class _BoomTracer:
        def span(self, name: str, attributes: Mapping[str, object] | None = None):
            raise RuntimeError("tracer exploded")

    tracing.set_tracer(_BoomTracer())
    ran = False
    # The tracer blows up opening the span, but the wrapped body MUST still run.
    with tracing.span("x") as s:
        s.set_attribute("k", "v")
        ran = True
    assert ran


def test_body_exceptions_propagate_through_span() -> None:
    tracing.set_tracer(_RecordingTracer())
    with pytest.raises(ValueError, match="boom"), tracing.span("x"):
        raise ValueError("boom")
