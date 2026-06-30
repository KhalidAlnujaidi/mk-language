"""Tests for daemon/backoff.py — the exponential-backoff schedule (pure math)."""

from __future__ import annotations

import pytest
from daemon.backoff import RetryPolicy


def test_first_attempt_is_immediate() -> None:
    assert RetryPolicy().delay_before(1) == 0.0


def test_delays_grow_geometrically() -> None:
    p = RetryPolicy(base_delay_s=0.5, factor=2.0, max_delay_s=100.0)
    assert p.delay_before(2) == 0.5
    assert p.delay_before(3) == 1.0
    assert p.delay_before(4) == 2.0


def test_delay_is_capped_at_max() -> None:
    p = RetryPolicy(base_delay_s=1.0, factor=10.0, max_delay_s=5.0)
    assert p.delay_before(2) == 1.0
    assert p.delay_before(3) == 5.0  # 10.0 capped to 5.0
    assert p.delay_before(9) == 5.0


def test_invalid_policy_rejected() -> None:
    with pytest.raises(ValueError):
        RetryPolicy(max_attempts=0)
    with pytest.raises(ValueError):
        RetryPolicy(base_delay_s=-1.0)
