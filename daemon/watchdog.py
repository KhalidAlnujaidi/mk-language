"""Watchdog restart policy (self-healing, vision §6 reactive).

Pure decisions a supervisor consumes: exponential backoff between restarts and a
circuit breaker that stops flapping after too many failures. The supervisor loop
itself (spawn/heartbeat/sleep) is a thin impure shell built on these.
"""

from __future__ import annotations


def backoff_delay(
    attempt: int, *, base: float = 1.0, factor: float = 2.0, cap: float = 60.0
) -> float:
    """Seconds to wait before restart *attempt* (0-based), exponential, capped."""
    return min(base * (factor**attempt), cap)


def should_restart(*, failures: int, max_failures: int) -> bool:
    """Whether to attempt another restart, or trip the breaker at *max_failures*."""
    return failures < max_failures
