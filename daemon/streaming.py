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
from collections.abc import AsyncIterator, Callable, Iterable, Iterator
from dataclasses import dataclass, field
from typing import cast

import httpx
from kernel.contracts import Tier
from kernel.jsonutil import as_dict, as_int

from daemon.backends import BackendSpec, default_specs
from daemon.exec import BackendError, BackendResponse, Messages

_DEFAULT_TIMEOUT_S = 120.0
_DATA_PREFIX = "data:"
_DONE = "[DONE]"


def _iter_events(lines: Iterable[str]) -> Iterator[dict[str, object]]:
    """Parse SSE *lines* into decoded ``data:`` event objects (pure, shared).

    Skips keep-alive blanks, SSE comments, and malformed JSON; stops at the
    ``data: [DONE]`` sentinel. This is the one place that understands the SSE
    framing — both the content-only and the full (tool-call) parsers build on it.
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
        yield as_dict(parsed)


def iter_content_deltas(lines: Iterable[str]) -> Iterator[str]:
    """Yield the assistant content deltas of an SSE stream (pure).

    Each ``choices[0].delta.content`` string, skipping tool-call-only deltas (no
    ``content``). The OpenAI/Ollama streaming shape — the same protocol the
    non-streaming path uses.
    """
    for event in _iter_events(lines):
        choices = event.get("choices")
        if not isinstance(choices, list) or not choices:
            continue
        first = as_dict(choices[0])  # type: ignore[arg-type]  # untyped JSON list
        delta = as_dict(first.get("delta"))
        content = delta.get("content")
        if isinstance(content, str) and content:
            yield content


@dataclass
class _ToolAcc:
    """Mutable accumulator for one streamed tool call (reassembled by index)."""

    id: str = ""
    name: str = ""
    arguments: str = ""

    def to_dict(self) -> dict[str, object]:
        return {
            "id": self.id,
            "type": "function",
            "function": {"name": self.name, "arguments": self.arguments},
        }


@dataclass
class StreamAccumulator:
    """Folds streamed SSE events into one :class:`BackendResponse`.

    Content deltas concatenate; tool-call deltas reassemble by ``index`` (id +
    name come once, ``arguments`` arrive in fragments); ``finish_reason`` and any
    ``usage`` are captured from whichever chunk carries them. This is what lets the
    agent loop consume a STREAM exactly as it consumes a single-shot response —
    the live tokens are a side effect, the reassembled result is identical.
    """

    exact: bool = True
    _content: list[str] = field(default_factory=list[str])
    _tools: dict[int, _ToolAcc] = field(default_factory=dict[int, "_ToolAcc"])
    _order: list[int] = field(default_factory=list[int])
    _finish: str | None = None
    _tokens_in: int | None = None
    _tokens_out: int | None = None

    def feed(self, event: dict[str, object]) -> str | None:
        """Fold one event; return its content delta (for live render) or None."""
        usage = as_dict(event.get("usage"))
        if usage:
            self._tokens_in = as_int(usage.get("prompt_tokens"))
            self._tokens_out = as_int(usage.get("completion_tokens"))
        choices = event.get("choices")
        if not isinstance(choices, list) or not choices:
            return None
        first = as_dict(choices[0])  # type: ignore[arg-type]  # untyped JSON list
        finish = first.get("finish_reason")
        if isinstance(finish, str):
            self._finish = finish
        delta = as_dict(first.get("delta"))
        raw_tcs = delta.get("tool_calls")
        if isinstance(raw_tcs, list):
            for frag in cast("list[object]", raw_tcs):
                self._merge_tool(as_dict(frag))
        content = delta.get("content")
        if isinstance(content, str) and content:
            self._content.append(content)
            return content
        return None

    def _merge_tool(self, frag: dict[str, object]) -> None:
        raw_idx = frag.get("index")
        idx = raw_idx if isinstance(raw_idx, int) else 0
        slot = self._tools.get(idx)
        if slot is None:
            slot = _ToolAcc()
            self._tools[idx] = slot
            self._order.append(idx)
        fid = frag.get("id")
        if isinstance(fid, str) and fid:
            slot.id = fid
        fn = as_dict(frag.get("function"))
        name = fn.get("name")
        if isinstance(name, str) and name:
            slot.name = name
        args = fn.get("arguments")
        if isinstance(args, str) and args:
            slot.arguments += args

    def build(self) -> BackendResponse:
        """The reassembled response — identical in shape to the single-shot path."""
        tool_calls = [self._tools[i].to_dict() for i in self._order] or None
        return BackendResponse(
            content="".join(self._content),
            tokens_in=self._tokens_in,
            tokens_out=self._tokens_out,
            tokens_exact=self.exact,
            tool_calls=tool_calls,
            finish_reason=self._finish,
        )


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


# --- Full streaming turn (content live + tool_calls reassembled) --------------


async def stream_response(
    base_url: str,
    tier: Tier,
    messages: Messages,
    *,
    on_content: Callable[[str], None],
    tools: list[dict[str, object]] | None = None,
    exact: bool = True,
    timeout: float = _DEFAULT_TIMEOUT_S,
    transport: httpx.AsyncBaseTransport | None = None,
    auth_token: str | None = None,
) -> BackendResponse:
    """Stream a completion, push content to *on_content* live, and return the FULL
    reassembled :class:`BackendResponse` (content + tool_calls + usage).

    This is what makes the agent loop streamable: it gets the same response shape
    it already consumes, while the answer renders token-by-token as a side effect.
    Failures map to a retryable ``BackendError`` so the caller falls back.
    """
    payload: dict[str, object] = {
        "model": tier.model_name,
        "messages": messages,
        "stream": True,
    }
    if tools:
        payload["tools"] = tools
    headers = {"Authorization": f"Bearer {auth_token}"} if auth_token else None
    acc = StreamAccumulator(exact=exact)
    try:
        async with httpx.AsyncClient(
            base_url=base_url, timeout=timeout, transport=transport, headers=headers
        ) as client, client.stream("POST", "/chat/completions", json=payload) as resp:
            if resp.status_code >= 400:  # noqa: PLR2004 — HTTP error class
                raise BackendError(f"backend {resp.status_code}", retryable=True)
            async for line in resp.aiter_lines():
                for event in _iter_events((line,)):
                    delta = acc.feed(event)
                    if delta:
                        on_content(delta)
    except BackendError:
        raise
    except httpx.HTTPError as exc:
        raise BackendError(f"backend transport: {exc}", retryable=True) from exc
    return acc.build()


async def stream_agent_turn(
    tier: Tier,
    messages: Messages,
    *,
    on_content: Callable[[str], None],
    tools: list[dict[str, object]] | None = None,
    specs: dict[str, BackendSpec] | None = None,
    timeout: float = _DEFAULT_TIMEOUT_S,
    transport: httpx.AsyncBaseTransport | None = None,
) -> BackendResponse:
    """Resolve *tier*'s backend (like :func:`daemon.backends.make_dispatch`) and
    stream one agent turn — live content via *on_content*, tool_calls reassembled
    into the returned response. Unknown backend → retryable ``BackendError``."""
    table = specs if specs is not None else default_specs()
    spec = table.get(tier.backend) if tier.backend is not None else None
    if spec is None:
        raise BackendError(f"no adapter for backend {tier.backend!r}", retryable=True)
    auth_token = os.environ.get(spec.auth_env) if spec.auth_env else None
    return await stream_response(
        spec.base_url,
        tier,
        messages,
        on_content=on_content,
        tools=tools,
        exact=spec.exact,
        timeout=timeout,
        transport=transport,
        auth_token=auth_token,
    )
