"""Streaming the agent's turn (vision §5.2 Layer 3 — live answer).

When ``on_token`` is wired, run_agent streams each turn: content renders live and
tool_calls are reassembled into the same response shape the loop already consumes.
On a stream failure it falls back to the non-streaming chain — so the agent never
loses a turn. Driven offline by a fake ``stream_agent_turn``.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable
from pathlib import Path
from typing import TypeVar

from daemon.exec import BackendError, BackendResponse
from kernel.contracts import Tier
from kernel.metrics import MetricsSink
from products.agent.loop import run_agent
from products.agent.tools import Tool, ToolRegistry

TIER = Tier.model("gemma-agentic:32k", where="local", backend="ollama")
_T = TypeVar("_T")


def _run(coro: Awaitable[_T]) -> _T:
    return asyncio.run(coro)  # type: ignore[arg-type]


def _sink() -> MetricsSink:
    return MetricsSink(Path("/dev/null"))


def _tool_call(call_id: str, name: str, arguments: str) -> dict[str, object]:
    return {
        "id": call_id,
        "type": "function",
        "function": {"name": name, "arguments": arguments},
    }


def _echo_registry() -> ToolRegistry:
    reg = ToolRegistry()
    reg.register(
        Tool(
            name="echo",
            description="echo",
            parameters={"type": "object", "properties": {"x": {"type": "string"}}},
            handler=lambda a: f"echo:{a.get('x')}",
        )
    )
    return reg


def _scripted_factory(turns: list[BackendResponse]):
    box = {"i": 0}

    def factory(_schema: list[dict[str, object]]):
        async def call(_tier, _messages) -> BackendResponse:
            i = box["i"]
            box["i"] = i + 1
            return turns[min(i, len(turns) - 1)]

        return call

    return factory


def test_agent_streams_final_answer_and_dispatches_streamed_tool_calls(
    monkeypatch,
) -> None:
    turns = iter(
        [
            # turn 0: a streamed tool call (no content)
            BackendResponse(
                content="",
                tool_calls=[_tool_call("c1", "echo", '{"x": "hi"}')],
                finish_reason="tool_calls",
            ),
            # turn 1: the streamed final answer
            BackendResponse(content="done answer"),
        ]
    )

    async def fake_stream(_tier, _messages, *, on_content, tools=None, **_kw):
        resp = next(turns)
        for word in resp.content.split():
            on_content(word)  # stream the answer word-by-word
        return resp

    monkeypatch.setattr("daemon.streaming.stream_agent_turn", fake_stream)
    tokens: list[str] = []
    result = _run(
        run_agent(
            "task",
            tier=TIER,
            registry=_echo_registry(),
            sink=_sink(),
            task_id="t",
            on_token=tokens.append,
            max_turns=4,
        )
    )
    assert result.stopped == "complete"
    assert result.final_text == "done answer"
    assert tokens == ["done", "answer"]  # the final answer streamed live
    # the streamed tool call was reassembled and dispatched
    assert any(s.kind == "tool" and s.name == "echo" for s in result.steps)


def test_agent_falls_back_to_non_streaming_when_stream_fails(monkeypatch) -> None:
    async def boom(_tier, _messages, *, on_content, tools=None, **_kw):
        raise BackendError("backend does not stream")

    monkeypatch.setattr("daemon.streaming.stream_agent_turn", boom)
    fallback = _scripted_factory([BackendResponse(content="fallback answer")])
    result = _run(
        run_agent(
            "task",
            tier=TIER,
            registry=_echo_registry(),
            sink=_sink(),
            task_id="t",
            on_token=lambda _d: None,
            call_factory=fallback,
            max_turns=2,
        )
    )
    assert result.final_text == "fallback answer"  # the non-streaming chain answered
    assert result.stopped == "complete"
