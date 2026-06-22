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

import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from kernel.contracts import EventRecord, Tier

# --- Injected backend boundary -----------------------------------------------

#: Messages are OpenAI-shape chat dicts: ``{"role": ..., "content": ...}``.
Messages = list[dict[str, str]]


@dataclass(frozen=True)
class BackendResponse:
    """A successful backend completion.

    ``tokens_exact`` is ``True`` for a local backend (Ollama returns exact
    counts) and ``False`` for a cloud backend (counts are estimates). Token
    counts may be ``None`` when the backend did not report them.
    """

    content: str
    tokens_in: int | None = None
    tokens_out: int | None = None
    tokens_exact: bool = True


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


# --- Executor -----------------------------------------------------------------


async def execute(
    chain: list[Tier],
    messages: Messages,
    *,
    call: Call,
    task_id: str,
    kind: str = "chat",
    sample_vram: VramSampler | None = None,
) -> ExecResult:
    """Walk *chain*, executing on the first tier that succeeds.

    Each tier is tried via *call*; any failure is absorbed (the broker fails
    SOFT, spec §6) and the next tier is tried. On success an ``ExecResult`` is
    returned with an exact-token ``EventRecord`` and a best-effort VRAM delta.

    Raises ``ChainExhausted`` — carrying a failure ``EventRecord`` (so the log
    has no silent gap) — when every tier fails or the chain is empty.
    """
    last_tier: Tier | None = None

    for tier in chain:
        last_tier = tier
        before = sample_vram() if sample_vram is not None else None
        started = time.perf_counter()
        try:
            response = await call(tier, messages)
        except BackendError:
            # Fail soft: absorb and fall through to the next tier.
            continue
        latency_ms = (time.perf_counter() - started) * 1000.0
        after = sample_vram() if sample_vram is not None else None

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
