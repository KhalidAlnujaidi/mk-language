"""Multi-backend adapter layer (broker M2 depth, vision §5.3).

Ollama, vLLM, and llama.cpp all expose the **same** OpenAI-compatible
``/v1/chat/completions`` endpoint, so the broker needs only ONE generic
transport — :func:`openai_compatible_call` — parameterised by base URL, plus a
:func:`make_dispatch` that selects the backend for a tier by ``tier.backend``.
The genuine reuse (Rule Zero) is the OpenAI protocol the three backends already
implement; we do not write three translators.

A backend with no configured adapter (an unknown name, or the cloud
``anthropic`` backend, which speaks a different protocol and is out of scope this
increment) raises a retryable :class:`~daemon.exec.BackendError` so the executor
falls through to the next tier — never a silent misroute (the broker fails SOFT,
spec §6).

The httpx transport is injectable (``transport=``) so the suite runs offline
against ``httpx.MockTransport`` — no network, no live server.
"""

from __future__ import annotations

from dataclasses import dataclass

import httpx
from kernel.contracts import Tier
from kernel.jsonutil import as_dict, as_int
from kernel.manifest import local_backend_urls

from daemon.exec import BackendError, BackendResponse, Call, Messages

_DEFAULT_TIMEOUT_S = 120.0


@dataclass(frozen=True)
class BackendSpec:
    """How to reach one backend: its OpenAI-compatible base URL + whether its
    token counts are exact. All three local backends report exact usage."""

    base_url: str
    exact: bool = True


def backend_specs() -> dict[str, BackendSpec]:
    """The configured local-backend table, one spec per backend.

    Base URLs come from :func:`kernel.manifest.local_backend_urls` — the single
    source of truth the probe also reads, so dispatch and discovery always agree
    on where each backend lives. All local backends report exact token counts.
    """
    return {name: BackendSpec(url) for name, url in local_backend_urls().items()}


# --- The generic OpenAI-compatible transport ---------------------------------


async def openai_compatible_call(
    base_url: str,
    tier: Tier,
    messages: Messages,
    *,
    exact: bool = True,
    timeout: float = _DEFAULT_TIMEOUT_S,
    transport: httpx.AsyncBaseTransport | None = None,
) -> BackendResponse:
    """Execute one chat completion against an OpenAI-compatible *base_url*.

    Maps transport/timeout/5xx failures to a retryable ``BackendError`` so the
    executor falls through to the next tier. ``tokens_exact`` is set from *exact*
    (``True`` for local backends; never claim cloud counts are exact). The
    optional *transport* is injected in tests; ``None`` uses the real network.
    """
    payload = {"model": tier.model_name, "messages": messages, "stream": False}
    try:
        async with httpx.AsyncClient(
            base_url=base_url, timeout=timeout, transport=transport
        ) as client:
            resp = await client.post("/chat/completions", json=payload)
            if resp.status_code >= 500:
                raise BackendError(f"backend {resp.status_code}", retryable=True)
            resp.raise_for_status()
            data: dict[str, object] = resp.json()
    except BackendError:
        raise
    except httpx.HTTPError as exc:
        raise BackendError(f"backend transport: {exc}", retryable=True) from exc

    raw_choices = data.get("choices")
    if not isinstance(raw_choices, list) or not raw_choices:
        raise BackendError("backend returned no choices", retryable=True)
    choices: list[object] = list(raw_choices)  # type: ignore[arg-type]  # untyped JSON
    first = as_dict(choices[0])
    message = as_dict(first.get("message"))
    content = message.get("content", "")
    usage = as_dict(data.get("usage"))
    return BackendResponse(
        content=str(content),
        tokens_in=as_int(usage.get("prompt_tokens")),
        tokens_out=as_int(usage.get("completion_tokens")),
        tokens_exact=exact,
    )


# --- The dispatcher -----------------------------------------------------------


def make_dispatch(
    specs: dict[str, BackendSpec] | None = None,
    *,
    timeout: float = _DEFAULT_TIMEOUT_S,
    transport: httpx.AsyncBaseTransport | None = None,
) -> Call:
    """Build a backend-dispatching ``Call`` for the executor.

    The returned coroutine routes each tier to its backend's transport by
    ``tier.backend``. A tier whose backend has no adapter (unknown name, or the
    out-of-scope ``anthropic`` cloud backend) raises a retryable ``BackendError``
    so the executor falls through — never a silent misroute (spec §6).
    """
    table = specs if specs is not None else backend_specs()

    async def dispatch(tier: Tier, messages: Messages) -> BackendResponse:
        spec = table.get(tier.backend) if tier.backend is not None else None
        if spec is None:
            raise BackendError(
                f"no adapter for backend {tier.backend!r}", retryable=True
            )
        return await openai_compatible_call(
            spec.base_url,
            tier,
            messages,
            exact=spec.exact,
            timeout=timeout,
            transport=transport,
        )

    return dispatch
