"""Distributed tracing for the standalone broker daemon (vision §7).

Proves the broker process emits spans AND joins an external caller's trace via the
W3C ``traceparent`` header — the cross-process stitch the in-process trace can't
do on its own. Skipped without the optional ``otel`` extra.
"""
# fastapi's TestClient return types are untyped here; scope the unknown rules off.
# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false, reportUnknownArgumentType=false

from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("opentelemetry")

from daemon.exec import BackendResponse, Messages  # noqa: E402
from daemon.server import BrokerConfig, create_app  # noqa: E402
from daemon.tracing import _OtelTracer, incoming_trace, init_tracing  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from kernel.contracts import Tier  # noqa: E402
from kernel.manifest import LocalModel, Manifest  # noqa: E402
from kernel.tracing import set_tracer  # noqa: E402
from opentelemetry.sdk.trace import TracerProvider  # noqa: E402
from opentelemetry.sdk.trace.export import SimpleSpanProcessor  # noqa: E402
from opentelemetry.sdk.trace.export.in_memory_span_exporter import (  # noqa: E402
    InMemorySpanExporter,
)

_REMOTE_TRACE = "0af7651916cd43dd8448eb211c80319c"
_TRACEPARENT = f"00-{_REMOTE_TRACE}-b7ad6b7169203331-01"


def _manifest(**_kw: object) -> Manifest:
    return Manifest(
        cpu_count=8,
        ram_gb=60.0,
        gpu_vram_gb=20.0,
        local_models=(LocalModel("small", 4.0),),
        cloud_available=False,
    )


async def _ok_call(_tier: Tier, _messages: Messages) -> BackendResponse:
    return BackendResponse(content="ok", tokens_in=1, tokens_out=1)


@pytest.fixture
def exporter() -> InMemorySpanExporter:
    exp = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exp))
    set_tracer(_OtelTracer(provider.get_tracer("test")))
    yield exp
    set_tracer(None)


def _client() -> TestClient:
    # No `with`: skip the lifespan so its init_tracing() does not replace the
    # in-memory tracer the fixture installed.
    config = BrokerConfig(
        probe=_manifest, call=_ok_call, metrics_path=Path("/dev/null")
    )
    return TestClient(create_app(config))


def test_init_tracing_disabled_returns_false() -> None:
    set_tracer(None)
    assert init_tracing(enabled=False) is False


def test_incoming_trace_is_noop_when_disabled() -> None:
    set_tracer(None)  # no tracer installed → incoming_trace must not raise
    with incoming_trace({"traceparent": _TRACEPARENT}):
        pass


def test_broker_joins_the_callers_trace(exporter: InMemorySpanExporter) -> None:
    resp = _client().post(
        "/v1/chat/completions",
        json={"messages": [{"role": "user", "content": "hi"}]},
        headers={"traceparent": _TRACEPARENT},
    )
    assert resp.status_code == 200
    spans = exporter.get_finished_spans()
    assert "broker.execute" in {s.name for s in spans}
    bx = next(s for s in spans if s.name == "broker.execute")
    # The broker's spans share the CALLER's trace id — one trace across processes.
    assert format(bx.context.trace_id, "032x") == _REMOTE_TRACE


def test_broker_roots_its_own_trace_without_traceparent(
    exporter: InMemorySpanExporter,
) -> None:
    resp = _client().post(
        "/v1/chat/completions",
        json={"messages": [{"role": "user", "content": "hi"}]},
    )
    assert resp.status_code == 200
    spans = exporter.get_finished_spans()
    bx = next(s for s in spans if s.name == "broker.execute")
    # No remote parent → the broker still traces, under its own (different) id.
    assert format(bx.context.trace_id, "032x") != _REMOTE_TRACE
