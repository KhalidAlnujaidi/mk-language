"""Streaming chat completions (vision §5.2 Layer 3 — live token output).

The pure SSE parser is exercised across every shape; the async transport is
driven by an injected httpx MockTransport so it runs offline. Failures must map
to a retryable BackendError (so the caller falls back to the non-streaming path).
"""

from __future__ import annotations

import asyncio
import json

import httpx
import pytest
from daemon.exec import BackendError
from daemon.streaming import (
    StreamAccumulator,
    iter_content_deltas,
    stream_chat,
    stream_completion,
    stream_response,
)
from kernel.contracts import Tier

_TIER = Tier.model("m", where="local", backend="ollama")


def _event(obj: dict) -> str:
    return f"data: {json.dumps(obj)}\n\n"


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


# --- the full accumulator (content live + tool_calls reassembled) -------------


def test_accumulator_reassembles_content_and_tool_calls() -> None:
    acc = StreamAccumulator()
    assert acc.feed({"choices": [{"delta": {"content": "Hi"}}]}) == "Hi"
    acc.feed(
        {
            "choices": [
                {"delta": {"tool_calls": [
                    {
                        "index": 0,
                        "id": "c1",
                        "function": {"name": "f", "arguments": "{"},
                    }
                ]}}
            ]
        }
    )
    acc.feed(
        {"choices": [{"delta": {"tool_calls": [
            {"index": 0, "function": {"arguments": "}"}}
        ]}}]}
    )
    acc.feed(
        {
            "choices": [{"delta": {}, "finish_reason": "tool_calls"}],
            "usage": {"prompt_tokens": 5, "completion_tokens": 2},
        }
    )
    r = acc.build()
    assert r.content == "Hi"
    assert r.tool_calls == [
        {"id": "c1", "type": "function", "function": {"name": "f", "arguments": "{}"}}
    ]
    assert r.finish_reason == "tool_calls"
    assert r.tokens_in == 5 and r.tokens_out == 2  # noqa: PLR2004


def test_stream_response_reassembles_tool_calls_over_the_wire() -> None:
    frag1 = {
        "index": 0,
        "id": "c1",
        "function": {"name": "read_file", "arguments": '{"p'},
    }
    frag2 = {"index": 0, "function": {"arguments": 'ath":1}'}}
    body = (
        _event({"choices": [{"delta": {"tool_calls": [frag1]}}]})
        + _event({"choices": [{"delta": {"tool_calls": [frag2]}}]})
        + _event({"choices": [{"delta": {}, "finish_reason": "tool_calls"}]})
        + "data: [DONE]\n\n"
    ).encode()

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=body)

    got: list[str] = []

    async def go():
        return await stream_response(
            "http://x/v1",
            _TIER,
            [],
            on_content=got.append,
            transport=httpx.MockTransport(handler),
        )

    resp = asyncio.run(go())
    assert got == []  # a tool-call turn streams no content
    assert resp.tool_calls == [
        {
            "id": "c1",
            "type": "function",
            "function": {"name": "read_file", "arguments": '{"path":1}'},
        }
    ]
    assert resp.finish_reason == "tool_calls"


def test_stream_response_streams_content_and_returns_full() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=_sse_body("Hel", "lo"))

    got: list[str] = []

    async def go():
        return await stream_response(
            "http://x/v1",
            _TIER,
            [],
            on_content=got.append,
            transport=httpx.MockTransport(handler),
        )

    resp = asyncio.run(go())
    assert got == ["Hel", "lo"]  # streamed live
    assert resp.content == "Hello"  # and the full text is returned
    assert resp.tool_calls is None
