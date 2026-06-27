"""Streaming chat completions (vision §5.2 Layer 3 — live token output).

The pure SSE parser is exercised across every shape; the async transport is
driven by an injected httpx MockTransport so it runs offline. Failures must map
to a retryable BackendError (so the caller falls back to the non-streaming path).
"""

from __future__ import annotations

import asyncio

import httpx
import pytest
from daemon.exec import BackendError
from daemon.streaming import iter_content_deltas, stream_chat, stream_completion
from kernel.contracts import Tier

_TIER = Tier.model("m", where="local", backend="ollama")


def test_iter_content_deltas_yields_in_order_and_stops_at_done() -> None:
    lines = [
        'data: {"choices":[{"delta":{"content":"Hel"}}]}',
        'data: {"choices":[{"delta":{"content":"lo"}}]}',
        "data: [DONE]",
        'data: {"choices":[{"delta":{"content":"after-done"}}]}',
    ]
    assert list(iter_content_deltas(lines)) == ["Hel", "lo"]


def test_iter_content_deltas_skips_noise() -> None:
    lines = [
        "",  # keep-alive blank
        ": this is an SSE comment",
        "data: not-json",  # malformed
        'data: {"choices":[]}',  # no choices
        'data: {"choices":[{"delta":{}}]}',  # no content
        'data: {"choices":[{"delta":{"content":""}}]}',  # empty content
        'data: {"choices":[{"delta":{"tool_calls":[{}]}}]}',  # tool-call only
        'data: {"choices":[{"delta":{"content":"x"}}]}',
    ]
    assert list(iter_content_deltas(lines)) == ["x"]


def _sse_body(*chunks: str) -> bytes:
    events = "".join(
        f'data: {{"choices":[{{"delta":{{"content":"{c}"}}}}]}}\n\n' for c in chunks
    )
    return (events + "data: [DONE]\n\n").encode()


def test_stream_completion_yields_deltas() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=_sse_body("a", "b", "c"))

    transport = httpx.MockTransport(handler)

    async def go() -> list[str]:
        return [
            d
            async for d in stream_completion(
                "http://x/v1",
                _TIER,
                [{"role": "user", "content": "hi"}],
                transport=transport,
            )
        ]

    assert asyncio.run(go()) == ["a", "b", "c"]


def test_stream_completion_error_status_raises_backenderror() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, content=b"")

    transport = httpx.MockTransport(handler)

    async def go() -> list[str]:
        return [
            d
            async for d in stream_completion(
                "http://x/v1", _TIER, [], transport=transport
            )
        ]

    with pytest.raises(BackendError):
        asyncio.run(go())


def test_stream_chat_unknown_backend_raises_backenderror() -> None:
    bad = Tier.model("m", where="local", backend="no-such-backend")

    async def go() -> list[str]:
        return [d async for d in stream_chat(bad, [])]

    with pytest.raises(BackendError):
        asyncio.run(go())
