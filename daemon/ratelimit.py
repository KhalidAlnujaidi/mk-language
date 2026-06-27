"""Per-key rate-limit ledger (harvested from ``cheatcodes/freellmapi``).

freellmapi's ``server/src/services/ratelimit.ts`` tracks sliding RPM/TPM/TPD
windows per provider+key and honours ``Retry-After`` on a 429. We steal the
*algorithm* (a few dozen lines), not the service — it lands here in the daemon
layer so the brain chain can skip a tier it knows is rate-limited instead of
spending a round-trip to discover it (thesis #1: a rate limit is ground truth —
deterministic, countable, no model needed to predict a 429).

The ledger is **pure and time-injected**: every method takes ``now`` (a
monotonic float, seconds), so the suite runs offline with a fake clock and the
caller owns the one ``time.monotonic()`` read. Fail-direction is the caller's:
the brain chain fails SOFT, so a key in cooldown is *skipped*, not an error.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field

_MINUTE = 60.0
_DAY = 86_400.0


@dataclass(frozen=True)
class RateLimit:
    """Ceilings for one key. ``None`` means "no limit on this axis"."""

    rpm: int | None = None  # requests per minute
    tpm: int | None = None  # tokens per minute
    tpd: int | None = None  # tokens per day


@dataclass(frozen=True)
class Decision:
    """The verdict for an attempted call.

    ``allowed`` is the gate; ``retry_after_s`` is how long until the call would
    be allowed (``0.0`` when allowed now); ``reason`` names the binding limit
    for the audit log.
    """

    allowed: bool
    retry_after_s: float
    reason: str


def _new_events() -> deque[tuple[float, int]]:
    """Typed default factory for ``_KeyState.events`` (keeps pyright strict)."""
    return deque()


@dataclass
class _KeyState:
    """Sliding-window bookkeeping for a single key."""

    # (timestamp, tokens) events, oldest first. One deque covers both the
    # per-minute and per-day windows; we prune to the longest (day) horizon.
    events: deque[tuple[float, int]] = field(default_factory=_new_events)
    cooldown_until: float = 0.0  # set from a 429 Retry-After


class RateLimitLedger:
    """Tracks sliding RPM/TPM/TPD usage and 429 cooldowns per key.

    A *key* is any opaque string the caller chooses — by convention
    ``f"{backend}:{model}"`` or ``f"{backend}:{model}:{key_fingerprint}"``. The
    ledger never sees the secret itself, only the caller's chosen label.
    """

    def __init__(self, limits: dict[str, RateLimit] | None = None) -> None:
        self._limits = limits or {}
        self._state: dict[str, _KeyState] = {}

    def _prune(self, st: _KeyState, now: float) -> None:
        horizon = now - _DAY
        while st.events and st.events[0][0] < horizon:
            st.events.popleft()

    def _window_sums(
        self, st: _KeyState, now: float
    ) -> tuple[int, int, int]:
        """Return (requests_last_min, tokens_last_min, tokens_last_day)."""
        minute_floor = now - _MINUTE
        req_min = 0
        tok_min = 0
        tok_day = 0
        for ts, tokens in st.events:
            tok_day += tokens
            if ts >= minute_floor:
                req_min += 1
                tok_min += tokens
        return req_min, tok_min, tok_day

    def allow(self, key: str, now: float, *, est_tokens: int = 0) -> Decision:
        """Would a call on *key* be within limits at *now*?

        *est_tokens* is an optional pre-estimate of the call's token cost,
        counted against the TPM/TPD ceilings so a known-large call is held back
        before it pushes the window over. A key in 429 cooldown is denied until
        its ``cooldown_until``.
        """
        st = self._state.get(key)
        limit = self._limits.get(key, RateLimit())
        if st is None:
            # No history: only an active cooldown could block, and there is none.
            return Decision(True, 0.0, "ok")

        if now < st.cooldown_until:
            return Decision(
                False, st.cooldown_until - now, "cooldown (429 Retry-After)"
            )

        self._prune(st, now)
        req_min, tok_min, tok_day = self._window_sums(st, now)

        if limit.rpm is not None and req_min >= limit.rpm:
            return Decision(False, self._oldest_in_minute_expiry(st, now), "rpm")
        if limit.tpm is not None and tok_min + est_tokens > limit.tpm:
            return Decision(False, self._oldest_in_minute_expiry(st, now), "tpm")
        if limit.tpd is not None and tok_day + est_tokens > limit.tpd:
            return Decision(False, _DAY, "tpd")
        return Decision(True, 0.0, "ok")

    def _oldest_in_minute_expiry(self, st: _KeyState, now: float) -> float:
        """Seconds until the oldest event in the minute window ages out."""
        minute_floor = now - _MINUTE
        for ts, _ in st.events:
            if ts >= minute_floor:
                return max(0.0, ts + _MINUTE - now)
        return 0.0

    def record(self, key: str, now: float, tokens: int) -> None:
        """Record one completed call of *tokens* against *key* at *now*."""
        st = self._state.setdefault(key, _KeyState())
        st.events.append((now, max(0, tokens)))
        self._prune(st, now)

    def penalize(self, key: str, now: float, *, retry_after_s: float) -> None:
        """Apply a 429 cooldown to *key*: no calls until ``now + retry_after_s``."""
        st = self._state.setdefault(key, _KeyState())
        st.cooldown_until = max(st.cooldown_until, now + max(0.0, retry_after_s))
