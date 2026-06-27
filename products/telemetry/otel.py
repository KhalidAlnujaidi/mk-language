"""OpenTelemetry binding for the kernel tracing seam (vision §7).

Installs a real OTel-backed tracer into :mod:`kernel.tracing` so the ``span(...)``
calls scattered across groom → route → agent → broker emit one connected trace.
OpenTelemetry is an OPTIONAL dependency (the ``otel`` extra): everything here
imports it lazily inside :func:`init_tracing`, so importing this module never
requires it. Fail-soft (thesis #2): tracing off, OTel not installed, or any setup
error → :func:`init_tracing` returns ``False`` and the kernel keeps its no-op
tracer, so the framework runs unchanged.

Enable with ``KINOX_OTEL=1``. Spans export to an OTLP collector when
``OTEL_EXPORTER_OTLP_ENDPOINT`` is set, otherwise to the console (so a single
trace is visible locally with no collector to stand up).
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from contextlib import contextmanager

from kernel.tracing import set_tracer

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

    ``start_as_current_span`` makes the new span the active one for the duration
    of the block, so spans opened deeper in the call stack automatically become
    its children — that is what stitches the in-process pipeline into one trace.
    """

    def __init__(self, otel_tracer: object) -> None:
        self._t = otel_tracer

    @contextmanager
    def span(self, name: str, attributes: Mapping[str, object] | None = None):
        with self._t.start_as_current_span(name) as otel_span:  # type: ignore[attr-defined]
            if attributes:
                for key, value in attributes.items():
                    otel_span.set_attribute(key, _coerce(value))
            yield otel_span


def init_tracing(service_name: str = "kinox", *, enabled: bool | None = None) -> bool:
    """Wire OpenTelemetry into the kernel tracing seam; return whether it is live.

    No-op and ``False`` when tracing is disabled (``KINOX_OTEL`` unset) or
    OpenTelemetry is not installed or setup fails — the kernel keeps its no-op
    tracer. ``True`` when a real tracer was installed. Safe to call more than once
    (the last call wins); pass ``enabled=`` to force the decision in tests.
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
        set_tracer(_OtelTracer(trace.get_tracer("kinox")))
        return True
    except Exception:  # noqa: BLE001 — tracing must never block startup
        return False
