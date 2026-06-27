"""Streaming chat completions for live token-by-token output (vision §5.2 Layer 3).

The executor path (``daemon/exec.py``) is request → full ``BackendResponse``, which
the agent loop needs (it inspects ``tool_calls``). Plain chat replies, though, can
stream: this module adds a *separate*, fail-soft streaming path so the TUI can
render the brain's answer as it arrives, without disturbing the executor.

Split for testability the kernel way:
  - :func:`iter_content_deltas` is a PURE SSE parser (lines → content deltas), so
    every shape (deltas, ``[DONE]``, keep-alives, malformed JSON) is unit-tested
    with no network.
  - :func:`stream_completion` / :func:`stream_chat` are the thin async transports
    over httpx, mapping failures to a retryable ``BackendError`` so the caller can
    fall back to the non-streaming path (never a dead reply).
"""

from __future__ import annotations

import json
import os
from collections.abc import AsyncIterator, Iterable, Iterator

import httpx
from kernel.contracts import Tier
from kernel.jsonutil import as_dict

from daemon.backends import BackendSpec, default_specs
from daemon.exec import BackendError, Messages

_DEFAULT_TIMEOUT_S = 120.0
_DATA_PREFIX = "data:"
_DONE = "[DONE]"


def iter_content_deltas(lines: Iterable[str]) -> Iterator[str]:
    """Parse Server-Sent-Event *lines* into assistant content deltas (pure).

    Yields the ``choices[0].delta.content`` string of each ``data:`` event,
    skipping keep-alive blanks, SSE comments, malformed JSON, and tool-call-only
    deltas (no ``content``). Stops at the ``data: [DONE]`` sentinel. This is the
    OpenAI/Ollama streaming shape — the same protocol the non-streaming path uses.
    """
    for raw in lines:
        line = raw.strip()
        if not line or not line.startswith(_DATA_PREFIX):
            continue
        payload = line[len(_DATA_PREFIX) :].strip()
        if payload == _DONE:
            return
        try:
            parsed: object = json.loads(payload)
        except json.JSONDecodeError:
            continue
        data = as_dict(parsed)
        choices = data.get("choices")
        if not isinstance(choices, list) or not choices:
            continue
        first = as_dict(choices[0])  # type: ignore[arg-type]  # untyped JSON list
        delta = as_dict(first.get("delta"))
        content = delta.get("content")
        if isinstance(content, str) and content:
            yield content


async def stream_completion(
    base_url: str,
    tier: Tier,
    messages: Messages,
    *,
    timeout: float = _DEFAULT_TIMEOUT_S,
    transport: httpx.AsyncBaseTransport | None = None,
    auth_token: str | None = None,
) -> AsyncIterator[str]:
    """Stream one chat completion from an OpenAI-compatible *base_url*.

    Sends ``stream: true`` and yields content deltas as they arrive. Any
    transport/4xx/5xx failure becomes a retryable ``BackendError`` so the caller
    falls back to the non-streaming path. *transport* is injected in tests.
    """
    payload: dict[str, object] = {
        "model": tier.model_name,
        "messages": messages,
        "stream": True,
    }
    headers = {"Authorization": f"Bearer {auth_token}"} if auth_token else None
    try:
        async with httpx.AsyncClient(
            base_url=base_url, timeout=timeout, transport=transport, headers=headers
        ) as client, client.stream(
            "POST", "/chat/completions", json=payload
        ) as resp:
            if resp.status_code >= 400:  # noqa: PLR2004 — HTTP error class
                raise BackendError(f"backend {resp.status_code}", retryable=True)
            async for line in resp.aiter_lines():
                for delta in iter_content_deltas((line,)):
                    yield delta
    except BackendError:
        raise
    except httpx.HTTPError as exc:
        raise BackendError(f"backend transport: {exc}", retryable=True) from exc


async def stream_chat(
    tier: Tier,
    messages: Messages,
    *,
    specs: dict[str, BackendSpec] | None = None,
    timeout: float = _DEFAULT_TIMEOUT_S,
    transport: httpx.AsyncBaseTransport | None = None,
) -> AsyncIterator[str]:
    """Resolve *tier*'s backend (like :func:`daemon.backends.make_dispatch`) and
    stream its reply. Raises a retryable ``BackendError`` for an unknown backend so
    the caller can fall back — never a silent misroute (spec §6)."""
    table = specs if specs is not None else default_specs()
    spec = table.get(tier.backend) if tier.backend is not None else None
    if spec is None:
        raise BackendError(f"no adapter for backend {tier.backend!r}", retryable=True)
    auth_token = os.environ.get(spec.auth_env) if spec.auth_env else None
    async for delta in stream_completion(
        spec.base_url,
        tier,
        messages,
        timeout=timeout,
        transport=transport,
        auth_token=auth_token,
    ):
        yield delta
