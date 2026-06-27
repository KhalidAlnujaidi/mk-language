"""OpenTelemetry binding for the STANDALONE broker daemon (vision §7).

The broker runs as its own process (``uvicorn daemon.server:app``), separate from
the chat/agent process where :mod:`products.telemetry` installs the tracer. To
stitch an external OpenAI-compatible caller into ONE trace, the daemon must:

  1. install its OWN OTel tracer into the kernel seam at startup (:func:`init_tracing`);
  2. extract the W3C ``traceparent`` from each incoming request and run the
     broker's spans under it (:func:`incoming_trace`), so they become children of
     the caller's trace.

The daemon may import only ``kernel`` + third-party — never ``products`` (see
test_architecture) — so this deliberately mirrors :mod:`products.telemetry.otel`
rather than importing it: a small, intentional duplication across a hard layer
boundary. Optional + fail-soft (thesis #2): ``KINOX_OTEL`` unset, OpenTelemetry
absent, or any error → silent no-op and the broker runs unchanged.
"""

from __future__ import annotations

import os
from collections.abc import Generator, Mapping
from contextlib import contextmanager
from typing import Any

from kernel.tracing import set_tracer, tracing_enabled

_TRUTHY = {"1", "true", "yes", "on"}


def _env_enabled() -> bool:
    return os.environ.get("KINOX_OTEL", "").strip().lower() in _TRUTHY


def _coerce(value: object) -> object:
    """OTel attribute values must be str/bool/int/float (or sequences thereof)."""
    if isinstance(value, (str, bool, int, float)):
        return value
    return str(value)


class _OtelTracer:
    """Adapts an OpenTelemetry tracer to the kernel ``Tracer`` protocol.

    The injected tracer is typed ``Any``: OpenTelemetry is an optional dependency
    whose types resolve only when installed, and the kernel ``Tracer`` protocol is
    the contract callers actually rely on. Mirrors products/telemetry/otel.py.
    """

    def __init__(self, otel_tracer: Any) -> None:
        self._t = otel_tracer

    @contextmanager
    def span(
        self, name: str, attributes: Mapping[str, object] | None = None
    ) -> Generator[Any, None, None]:
        with self._t.start_as_current_span(name) as otel_span:
            if attributes:
                for key, value in attributes.items():
                    otel_span.set_attribute(key, _coerce(value))
            yield otel_span


def init_tracing(
    service_name: str = "kinox-broker", *, enabled: bool | None = None
) -> bool:
    """Wire OpenTelemetry into the kernel seam for the broker; return if it is live.

    No-op + ``False`` when disabled (``KINOX_OTEL`` unset), OpenTelemetry is not
    installed, or setup fails — the kernel keeps its no-op tracer. ``True`` when a
    real tracer was installed. Pass ``enabled=`` to force the decision in tests.
    """
    if enabled is None:
        enabled = _env_enabled()
    if not enabled:
        return False
    try:
        from opentelemetry import trace
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import (
            BatchSpanProcessor,
            ConsoleSpanExporter,
        )

        if os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT"):
            from opentelemetry.exporter.otlp.proto.http.trace_exporter import (
                OTLPSpanExporter,
            )

            exporter = OTLPSpanExporter()
        else:
            exporter = ConsoleSpanExporter()

        provider = TracerProvider(
            resource=Resource.create({"service.name": service_name})
        )
        provider.add_span_processor(BatchSpanProcessor(exporter))
        trace.set_tracer_provider(provider)
        set_tracer(_OtelTracer(trace.get_tracer("kinox-broker")))
        return True
    except Exception:  # noqa: BLE001 — tracing must never block the broker
        return False


@contextmanager
def incoming_trace(headers: Mapping[str, str]):
    """Run the enclosed broker work under the trace carried in *headers*.

    Extracts the W3C ``traceparent`` (and friends) from the incoming request and
    attaches it as the current context, so spans opened inside (``broker.execute``
    et al.) become CHILDREN of the caller's remote span — one trace across the
    process boundary. A no-op when tracing is off or OpenTelemetry is unavailable
    (then the broker's spans simply root their own trace, or nothing at all).
    """
    if not tracing_enabled():
        yield
        return
    try:
        from opentelemetry import context as otel_context
        from opentelemetry.propagate import extract
    except Exception:  # noqa: BLE001 — propagation is best-effort
        yield
        return
    token = otel_context.attach(extract(dict(headers)))
    try:
        yield
    finally:
        otel_context.detach(token)
