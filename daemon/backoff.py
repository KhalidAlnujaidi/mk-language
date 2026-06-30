"""Exponential-backoff retry policy (CodeWhale Tier-2 harvest).

Ported from CodeWhale's ``JobManager`` retry scheduling: a failed attempt's next
try is ``now + base_delay * factor**(attempt-1)``, capped. The reusable piece is
the *schedule math*, vendored here as a pure, side-effect-free function so it is
trivially testable and so the one ``await sleep(...)`` stays at the call site (the
executor), not buried in a helper.

Why kinox wants it: the executor (``daemon/exec.py``) currently demotes to the
next fallback tier on the *first* transient error. But a network blip, a 5xx, or a
brief rate-limit on the *preferred* tier is not a reason to drop to a worse/cheaper
model — a short backoff-and-retry on the same tier rides out the blip and keeps
the agent on its best tier (thesis #1: the right tier matters; don't waste it).

Fail-direction (thesis #2): retry only ever *re-tries* — it never turns a hard
failure into a success. A non-retryable error or an exhausted budget still falls
through to the next tier exactly as before.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class RetryPolicy:
    """How many times, and how long apart, to retry one tier on a transient error.

    *max_attempts* counts the FIRST try too (``1`` = no retry, the legacy
    behaviour). *base_delay_s* is the wait before the first retry; each further
    retry multiplies by *factor*, capped at *max_delay_s*.
    """

    max_attempts: int = 3
    base_delay_s: float = 0.5
    factor: float = 2.0
    max_delay_s: float = 8.0

    def __post_init__(self) -> None:
        if self.max_attempts < 1:
            raise ValueError("max_attempts must be >= 1")
        if self.base_delay_s < 0 or self.max_delay_s < 0:
            raise ValueError("delays must be non-negative")

    def delay_before(self, attempt: int) -> float:
        """Seconds to wait *before* the given 1-based *attempt*.

        ``delay_before(1) == 0`` (the first try is immediate); ``delay_before(2)``
        is ``base_delay_s``; each later attempt scales by ``factor`` up to
        ``max_delay_s``. Out-of-range attempts clamp rather than raise.
        """
        if attempt <= 1:
            return 0.0
        raw = self.base_delay_s * (self.factor ** (attempt - 2))
        return min(raw, self.max_delay_s)
