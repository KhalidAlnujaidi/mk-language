"""Watchdog restart policy (self-healing, vision §6 reactive).

Pure backoff + circuit-breaker decisions; the actual process supervision is a
thin impure shell that consumes these.
"""

from __future__ import annotations

from daemon.watchdog import backoff_delay, should_restart


def test_backoff_grows_exponentially_then_caps():
    assert backoff_delay(0) == 1.0
    assert backoff_delay(1) == 2.0
    assert backoff_delay(2) == 4.0
    assert backoff_delay(10, cap=30.0) == 30.0  # capped


def test_should_restart_circuit_breaks_at_max():
    assert should_restart(failures=0, max_failures=3) is True
    assert should_restart(failures=2, max_failures=3) is True
    assert should_restart(failures=3, max_failures=3) is False
    assert should_restart(failures=9, max_failures=3) is False
