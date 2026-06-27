"""Telemetry wiring (outer layer): binds OpenTelemetry to the kernel seam."""

from __future__ import annotations

from products.telemetry.otel import init_tracing

__all__ = ["init_tracing"]
