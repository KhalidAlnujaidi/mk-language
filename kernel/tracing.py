"""Pluggable, dependency-free tracing seam (vision §7 observability).

The kernel stays stdlib-only and agent-agnostic, so it cannot import
OpenTelemetry. Instead it owns a tiny tracer *slot*: by default a no-op, so every
``span(...)`` call across the codebase is free and never fails. An outer layer
(:mod:`products.telemetry`) installs a real OTel-backed tracer at startup via
:func:`set_tracer`, and from then on the same ``span(...)`` calls emit real spans
with automatic parent/child nesting (OpenTelemetry tracks the active span in a
context variable, so spans nested in the call stack become child spans).

This mirrors :class:`kernel.metrics.MetricsSink`: the kernel owns the *interface*;
the outer layer owns the *dependency*. Fail-soft (thesis #2): no tracer installed,
or OpenTelemetry absent, or a tracer that misbehaves → silent no-op, and the
framework runs exactly as before. Spans never change behaviour, only observe it.
"""

from __future__ import annotations

from collections.abc import Mapping
from contextlib import AbstractContextManager, contextmanager
from typing import Protocol, runtime_checkable


@runtime_checkable
class Span(Protocol):
    """The minimal span surface the codebase uses (OTel's Span satisfies it)."""

    def set_attribute(self, key: str, value: object) -> None: ...


@runtime_checkable
class Tracer(Protocol):
    """A tracer factory: ``span`` opens a context-managed span by name."""

    def span(
        self, name: str, attributes: Mapping[str, object] | None = None
    ) -> AbstractContextManager[Span]: ...


class _NullSpan:
    """A span that records nothing — the zero-overhead default."""

    def set_attribute(self, key: str, value: object) -> None:  # noqa: D401
        return None


class _NullTracer:
    """The default tracer: every span is a no-op (tracing disabled)."""

    @contextmanager
    def span(self, name: str, attributes: Mapping[str, object] | None = None):
        yield _NullSpan()


_NULL: Tracer = _NullTracer()
_tracer: Tracer = _NULL


def set_tracer(tracer: Tracer | None) -> None:
    """Install the active tracer (outer layer). ``None`` restores the no-op."""
    global _tracer
    _tracer = tracer if tracer is not None else _NULL


def get_tracer() -> Tracer:
    """The currently installed tracer (the no-op default until one is set)."""
    return _tracer


def tracing_enabled() -> bool:
    """True once a real (non-null) tracer has been installed."""
    return _tracer is not _NULL


@contextmanager
def span(name: str, attributes: Mapping[str, object] | None = None):
    """Open a span around a block; a no-op unless a real tracer is installed.

    Fail-soft by construction: if the tracer raises while *opening* the span we
    fall back to a no-op span, so instrumentation can never break the traced code.
    Exceptions raised inside the block propagate normally (and a real tracer
    records them) — only the tracer's own failures are swallowed.
    """
    tracer = _tracer
    try:
        ctx = tracer.span(name, attributes)
    except Exception:  # noqa: BLE001 — a tracer must never break the work it wraps
        ctx = _NULL.span(name, attributes)
    with ctx as active:
        yield active
