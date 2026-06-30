"""The fallback-walking executor (broker brick 1, spec §4.2).

``execute`` walks a fallback chain of model tiers, trying each in turn through an
*injected* backend ``call``. On the first success it returns an ``ExecResult``
carrying the content, the tier used, an honest ``EventRecord``, and a best-effort
VRAM delta. On a failure it falls through to the next tier; when the whole chain
is exhausted it raises ``ChainExhausted`` — which still carries an
``EventRecord`` so the metrics log never has a silent gap (spec §6).

The backend boundary is injected (``call``) so the unit tests run offline with
fakes — the real httpx → Ollama transport lives in ``daemon/server.py`` and is
injected here at request time. The kernel is never imported in reverse.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING

from kernel.contracts import EventRecord, Tier
from kernel.tracing import span

from daemon.backoff import RetryPolicy

if TYPE_CHECKING:
    # Type-only import to avoid a runtime circular dependency (ratelimit imports
    # nothing from exec; exec references the type only for annotations).
    from daemon.ratelimit import RateLimitLedger

#: A sleeper for backoff waits. Injected in tests (so no real time passes); the
#: default is the real event-loop sleep.
Sleeper = Callable[[float], Awaitable[None]]

# --- Injected backend boundary -----------------------------------------------

#: Messages are OpenAI-shape chat dicts. For plain chat the values are strings
#: (``{"role": ..., "content": ...}``); agent turns add richer values — an
#: assistant message carries a ``tool_calls`` list, and a ``tool`` message carries
#: a ``tool_call_id`` — so the value type is ``object``, not ``str``.
Messages = list[dict[str, object]]


@dataclass(frozen=True)
class BackendResponse:
    """A successful backend completion.

    ``tokens_exact`` is ``True`` for a local backend (Ollama returns exact
    counts) and ``False`` for a cloud backend (counts are estimates). Token
    counts may be ``None`` when the backend did not report them.

    ``tool_calls`` carries the OpenAI-shape tool-call list when the model asked to
    call tools (``finish_reason == "tool_calls"``); ``None`` for a plain text
    completion. The agent loop (``products/agent/loop.py``) reads these; plain
    chat ignores them, so both fields default to ``None`` — fully backward
    compatible with the single-shot chat path.
    """

    content: str
    tokens_in: int | None = None
    tokens_out: int | None = None
    tokens_exact: bool = True
    tool_calls: list[dict[str, object]] | None = None
    finish_reason: str | None = None


class BackendError(Exception):
    """A backend call failed. ``retryable`` records whether a fall-through is
    warranted, but the executor fails SOFT and falls through on *any* error."""

    def __init__(self, message: str, *, retryable: bool = True) -> None:
        super().__init__(message)
        self.retryable = retryable


#: The injected transport: ``(tier, messages) -> awaitable BackendResponse``.
Call = Callable[[Tier, Messages], Awaitable[BackendResponse]]

#: A best-effort VRAM sampler (GB used), returning ``None`` when unavailable.
VramSampler = Callable[[], float | None]


# --- Results & exhaustion -----------------------------------------------------


@dataclass(frozen=True)
class ExecResult:
    """The outcome of a successful chain walk.

    ``vram_delta_gb`` is the best-effort VRAM change measured around the
    successful call, or ``None`` when it could not be sampled — never a
    fabricated ``0`` (honest observability, vision §4.6).
    """

    content: str
    tier_used: Tier
    event: EventRecord
    vram_delta_gb: float | None = None
    #: OpenAI-shape tool calls the model requested this turn (``None`` for a plain
    #: text answer). The agent loop dispatches these and feeds results back.
    tool_calls: list[dict[str, object]] | None = None
    finish_reason: str | None = None


class ChainExhausted(Exception):
    """Every tier in the chain failed (or the chain was empty).

    Carries the failure ``EventRecord`` so the caller can still record it; the
    server turns this into a soft OpenAI-shape 503 error (spec §6)."""

    def __init__(self, event: EventRecord) -> None:
        super().__init__("fallback chain exhausted")
        self.event = event


# --- Tier label ---------------------------------------------------------------


def tier_label(tier: Tier) -> str:
    """A stable, log-friendly string for a tier, e.g. ``model:local:llama3``."""
    if not tier.is_model:
        return "deterministic"
    return f"model:{tier.where}:{tier.model_name}"


def tier_key(tier: Tier) -> str:
    """A stable key for per-tier bookkeeping (e.g. the rate-limit ledger).

    Convention: ``backend:model`` — the backend identifies the rate-limit pool
    (per-key-per-provider), and the model distinguishes tiers within it.
    """
    return f"{tier.backend}:{tier.model_name}"


# --- Executor -----------------------------------------------------------------


async def _call_with_retry(
    call: Call,
    tier: Tier,
    messages: Messages,
    *,
    retry: RetryPolicy | None,
    sleep: Sleeper,
) -> BackendResponse | None:
    """Call one *tier*, retrying on *retryable* transient errors with backoff.

    Returns the response, or ``None`` to signal "give up on this tier, fall
    through" (legacy behaviour when *retry* is ``None`` — exactly one attempt).
    A non-retryable ``BackendError`` is never retried; a retryable one is retried
    up to ``retry.max_attempts`` with :meth:`RetryPolicy.delay_before` waits.

    Any exception that is **not** a ``BackendError`` (e.g. ``JSONDecodeError``,
    ``ConnectionResetError``) is treated as a non-retryable tier failure — fail
    SOFT, fall through — rather than crashing the executor. This honours the
    fail-soft contract: *any* failure is absorbed.
    """
    attempts = retry.max_attempts if retry is not None else 1
    for attempt in range(1, attempts + 1):
        try:
            return await call(tier, messages)
        except BackendError as exc:
            # Last attempt, no policy, or a hard error → stop retrying this tier.
            if retry is None or not exc.retryable or attempt == attempts:
                return None
            await sleep(retry.delay_before(attempt + 1))
        except Exception:
            # Unknown failure (not a BackendError): fail soft, don't crash.
            return None
    return None


async def execute(
    chain: list[Tier],
    messages: Messages,
    *,
    call: Call,
    task_id: str,
    kind: str = "chat",
    sample_vram: VramSampler | None = None,
    retry: RetryPolicy | None = None,
    sleep: Sleeper = asyncio.sleep,
    ledger: RateLimitLedger | None = None,
    now: Callable[[], float] = time.monotonic,
) -> ExecResult:
    """Walk *chain*, executing on the first tier that succeeds.

    Each tier is tried via *call*; any failure is absorbed (the broker fails
    SOFT, spec §6) and the next tier is tried. On success an ``ExecResult`` is
    returned with an exact-token ``EventRecord`` and a best-effort VRAM delta.

    *retry* (CodeWhale Tier-2), when given, retries a tier on a *retryable*
    transient error with exponential backoff *before* falling through — so a blip
    on the preferred tier does not needlessly demote to a worse one. ``None``
    keeps the legacy one-shot-per-tier behaviour exactly. *sleep* is injected so
    the backoff waits are instant under test.

    *ledger*, when given, is consulted before each tier attempt: a key in 429
    cooldown or over its RPM/TPM/TPD ceiling is **skipped** (not retried) — saving
    a network round-trip to discover what the ledger already knows. On success the
    call's tokens are recorded against the ledger; this is the integration point
    for :mod:`daemon.ratelimit` — the ledger is pure and time-injected via *now*,
    so the suite runs offline with a fake clock.

    Raises ``ChainExhausted`` — carrying a failure ``EventRecord`` (so the log
    has no silent gap) — when every tier fails or the chain is empty.
    """
    # The "broker" span of the end-to-end trace (vision §7): one per execute call,
    # with a child span per tier attempt. A no-op unless a tracer is installed.
    with span(
        "broker.execute",
        {"kinox.task_id": task_id, "kinox.kind": kind, "kinox.chain_len": len(chain)},
    ):
        last_tier: Tier | None = None

        for tier in chain:
            last_tier = tier

            # Rate-limit gate (thesis #1: a rate limit is ground truth). Skip a
            # tier the ledger says is rate-limited, saving a round-trip. A key in
            # cooldown or over its window is skipped, not an error (fail SOFT).
            if ledger is not None:
                key = tier_key(tier)
                decision = ledger.allow(key, now())
                if not decision.allowed:
                    with span("broker.tier", {"kinox.tier": tier_label(tier)}) as s:
                        s.set_attribute("kinox.hit", False)
                        s.set_attribute("kinox.skipped", f"rate-limit:{decision.reason}")
                    continue

            before = sample_vram() if sample_vram is not None else None
            started = time.perf_counter()
            with span("broker.tier", {"kinox.tier": tier_label(tier)}) as tier_span:
                response = await _call_with_retry(
                    call, tier, messages, retry=retry, sleep=sleep
                )
                tier_span.set_attribute("kinox.hit", response is not None)
            if response is None:
                # Fail soft: this tier gave up (after any retries) → next tier.
                continue
            latency_ms = (time.perf_counter() - started) * 1000.0
            after = sample_vram() if sample_vram is not None else None

            # Record successful usage against the rate-limit ledger.
            if ledger is not None:
                key = tier_key(tier)
                tokens = (response.tokens_in or 0) + (response.tokens_out or 0)
                ledger.record(key, now(), tokens)

            event = EventRecord(
                task_id=task_id,
                kind=kind,
                tier=tier_label(tier),
                tokens_in=response.tokens_in,
                tokens_out=response.tokens_out,
                tokens_exact=response.tokens_exact,
                latency_ms=latency_ms,
            )
            vram_delta = (
                after - before if (before is not None and after is not None) else None
            )
            return ExecResult(
                content=response.content,
                tier_used=tier,
                event=event,
                vram_delta_gb=vram_delta,
                tool_calls=response.tool_calls,
                finish_reason=response.finish_reason,
            )

        # Chain exhausted (or empty): emit a failure record, then raise.
        failure = EventRecord(
            task_id=task_id,
            kind=kind,
            tier=tier_label(last_tier) if last_tier is not None else "none",
            tokens_in=None,
            tokens_out=None,
            tokens_exact=False,
            latency_ms=None,
        )
        raise ChainExhausted(failure)
