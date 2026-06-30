"""Tests for daemon/ratelimit.py — the freellmapi sliding-window ledger.

Pure and time-injected: every assertion drives a fake monotonic clock, so the
suite runs offline with no real time passing.
"""

from __future__ import annotations

from daemon.ratelimit import Decision, RateLimit, RateLimitLedger


def test_unknown_key_is_allowed() -> None:
    led = RateLimitLedger({"k": RateLimit(rpm=2)})
    d = led.allow("k", now=100.0)
    assert d.allowed is True
    assert d.reason == "ok"


def test_rpm_ceiling_blocks_then_recovers() -> None:
    led = RateLimitLedger({"k": RateLimit(rpm=2)})
    led.record("k", now=100.0, tokens=0)
    led.record("k", now=100.5, tokens=0)
    blocked = led.allow("k", now=101.0)
    assert blocked.allowed is False
    assert blocked.reason == "rpm"
    # First event ages out of the minute window at t=160; allowed again after.
    assert led.allow("k", now=161.0).allowed is True


def test_tpm_counts_estimated_tokens_before_the_call() -> None:
    led = RateLimitLedger({"k": RateLimit(tpm=1000)})
    led.record("k", now=10.0, tokens=900)
    # 900 used + 200 estimated > 1000 → held back.
    d = led.allow("k", now=11.0, est_tokens=200)
    assert d.allowed is False
    assert d.reason == "tpm"
    # A smaller call still fits.
    assert led.allow("k", now=11.0, est_tokens=50).allowed is True


def test_tpd_window_spans_the_day() -> None:
    led = RateLimitLedger({"k": RateLimit(tpd=1000)})
    led.record("k", now=0.0, tokens=600)
    led.record("k", now=3600.0, tokens=600)  # 1h later, same day
    d = led.allow("k", now=7200.0)
    assert d.allowed is False
    assert d.reason == "tpd"


def test_429_cooldown_blocks_until_retry_after() -> None:
    led = RateLimitLedger()
    led.penalize("k", now=100.0, retry_after_s=30.0)
    blocked = led.allow("k", now=110.0)
    assert blocked.allowed is False
    assert "cooldown" in blocked.reason
    assert blocked.retry_after_s == 20.0
    # After the cooldown elapses the key is usable again.
    assert led.allow("k", now=131.0).allowed is True


def test_decision_is_frozen_dataclass() -> None:
    d = Decision(True, 0.0, "ok")
    assert (d.allowed, d.retry_after_s, d.reason) == (True, 0.0, "ok")
