"""The tool-calling agent loop, driven offline by a scripted backend.

Proves the loop: dispatches tool calls and feeds observations back, completes on
a plain-text answer, caps runaways at max_turns (fail-CLOSED), routes every call
through the guard (fail-CLOSED), and surfaces backend failure as an error result.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable
from pathlib import Path
from typing import TypeVar

from daemon.exec import BackendError, BackendResponse, Call, Messages
from kernel.contracts import Tier
from kernel.metrics import MetricsSink
from products.agent.loop import run_agent
from products.agent.tools import Tool, ToolRegistry, default_registry

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


def _scripted_factory(turns: list[BackendResponse]) -> object:
    """A call_factory that returns successive scripted backend responses,
    ignoring the tool schema it is handed (the model is faked)."""
    box = {"i": 0}

    def factory(_schema: list[dict[str, object]]) -> Call:
        async def call(_tier: Tier, _messages: Messages) -> BackendResponse:
            i = box["i"]
            box["i"] = i + 1
            return turns[min(i, len(turns) - 1)]

        return call

    return factory


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


def test_loop_dispatches_then_completes() -> None:
    factory = _scripted_factory(
        [
            BackendResponse(
                content="",
                tool_calls=[_tool_call("c1", "echo", '{"x": "hi"}')],
                finish_reason="tool_calls",
            ),
            BackendResponse(content="all done", finish_reason="stop"),
        ]
    )
    result = _run(
        run_agent(
            "do it",
            tier=TIER,
            registry=_echo_registry(),
            sink=_sink(),
            task_id="t",
            call_factory=factory,  # type: ignore[arg-type]
        )
    )
    assert result.stopped == "complete"
    assert result.final_text == "all done"
    assert result.turns == 2
    tool_steps = [s for s in result.steps if s.kind == "tool"]
    assert tool_steps and tool_steps[0].name == "echo"


def _capturing_factory(seen: dict[str, Messages]) -> object:
    """A call_factory that records the messages of the first turn, then completes."""

    def factory(_schema: list[dict[str, object]]) -> Call:
        async def call(_tier: Tier, messages: Messages) -> BackendResponse:
            seen.setdefault("m", list(messages))
            return BackendResponse(content="done", finish_reason="stop")

        return call

    return factory


def test_plan_injected_as_hint() -> None:
    # A prehook plan rides in as a system message the brain sees, framed as a hint.
    seen: dict[str, Messages] = {}
    _run(
        run_agent(
            "do it",
            tier=TIER,
            registry=_echo_registry(),
            sink=_sink(),
            task_id="t",
            plan="1. edit a.py\n2. run tests",
            call_factory=_capturing_factory(seen),  # type: ignore[arg-type]
        )
    )
    systems = [m["content"] for m in seen["m"] if m["role"] == "system"]
    assert any(
        "edit a.py" in str(c) and "hint, not a contract" in str(c) for c in systems
    )


def test_no_plan_means_no_hint() -> None:
    # Absent a plan (planner off/unavailable), the brain runs exactly as before.
    seen: dict[str, Messages] = {}
    _run(
        run_agent(
            "do it",
            tier=TIER,
            registry=_echo_registry(),
            sink=_sink(),
            task_id="t",
            call_factory=_capturing_factory(seen),  # type: ignore[arg-type]
        )
    )
    assert not any("[plan]" in str(m["content"]) for m in seen["m"])


def test_loop_caps_runaway_at_max_turns() -> None:
    # Model that NEVER stops calling tools → must be stopped fail-CLOSED.
    forever = BackendResponse(
        content="",
        tool_calls=[_tool_call("c", "echo", '{"x": "again"}')],
        finish_reason="tool_calls",
    )
    result = _run(
        run_agent(
            "loop forever",
            tier=TIER,
            registry=_echo_registry(),
            sink=_sink(),
            task_id="t",
            max_turns=3,
            call_factory=_scripted_factory([forever]),  # type: ignore[arg-type]
        )
    )
    assert result.stopped == "max_turns"
    assert result.turns == 3


def test_guard_blocks_call_fail_closed() -> None:
    calls: list[str] = []
    reg = ToolRegistry()
    reg.register(
        Tool(
            "danger",
            "",
            {"type": "object", "properties": {}},
            lambda _a: calls.append("ran") or "ran",  # type: ignore[func-returns-value]
        )
    )
    factory = _scripted_factory(
        [
            BackendResponse(
                content="",
                tool_calls=[_tool_call("c1", "danger", "{}")],
                finish_reason="tool_calls",
            ),
            BackendResponse(content="stopped", finish_reason="stop"),
        ]
    )
    result = _run(
        run_agent(
            "be careful",
            tier=TIER,
            registry=reg,
            sink=_sink(),
            task_id="t",
            guard=lambda name, _args: "denied" if name == "danger" else None,
            call_factory=factory,  # type: ignore[arg-type]
        )
    )
    assert calls == []  # handler never ran — guard failed CLOSED
    assert any(s.kind == "blocked" for s in result.steps)


def test_loop_records_every_turn_and_tool_to_log(tmp_path: Path) -> None:
    # Honest observability: each model turn AND each tool dispatch is a record.
    sink = MetricsSink(tmp_path / "events.jsonl")
    factory = _scripted_factory(
        [
            BackendResponse(
                content="",
                tool_calls=[_tool_call("c1", "echo", '{"x": "hi"}')],
                finish_reason="tool_calls",
            ),
            BackendResponse(content="done", finish_reason="stop"),
        ]
    )
    _run(
        run_agent(
            "task",
            tier=TIER,
            registry=_echo_registry(),
            sink=sink,
            task_id="job",
            call_factory=factory,  # type: ignore[arg-type]
        )
    )
    kinds = [e.kind for e in sink.read_all()]
    assert kinds.count("agent") == 2  # two model turns
    assert "agent_tool:echo" in kinds  # the tool dispatch


def test_repeated_idempotent_read_is_deduplicated(tmp_path: Path) -> None:
    """A second read_file for the same path returns a pointer, not the payload —
    deterministic anti-rot (the file content is injected once, not twice)."""
    (tmp_path / "a.txt").write_text("PAYLOAD-CONTENT", encoding="utf-8")
    reg = default_registry(tmp_path)  # read_file + list_dir
    read = _tool_call("c1", "read_file", '{"path": "a.txt"}')
    factory = _scripted_factory(
        [
            BackendResponse(content="", tool_calls=[read], finish_reason="tool_calls"),
            BackendResponse(content="", tool_calls=[read], finish_reason="tool_calls"),
            BackendResponse(content="done", finish_reason="stop"),
        ]
    )
    sink = MetricsSink(tmp_path / "events.jsonl")
    result = _run(
        run_agent(
            "read it twice",
            tier=TIER,
            registry=reg,
            sink=sink,
            task_id="t",
            call_factory=factory,  # type: ignore[arg-type]
        )
    )
    assert result.stopped == "complete"
    kinds = [e.kind for e in sink.read_all()]
    assert kinds.count("agent_tool:read_file") == 1  # served once
    assert kinds.count("agent_tool_cached:read_file") == 1  # second was deduped


def _recording_factory(turns: list[BackendResponse], seen: list[Messages]) -> object:
    """Like ``_scripted_factory`` but records the messages handed to each turn so a
    test can assert what the loop injected into context."""
    box = {"i": 0}

    def factory(_schema: list[dict[str, object]]) -> Call:
        async def call(_tier: Tier, messages: Messages) -> BackendResponse:
            seen.append([dict(m) for m in messages])
            i = box["i"]
            box["i"] = i + 1
            return turns[min(i, len(turns) - 1)]

        return call

    return factory


def test_prior_history_is_spliced_before_this_turn() -> None:
    """A multi-turn agent run remembers earlier turns: ``history`` is injected
    between the system prompt and this turn's task, so the model sees prior
    user/assistant pairs (fixes agent-turn amnesia)."""
    seen: list[Messages] = []
    factory = _recording_factory(
        [BackendResponse(content="answer", finish_reason="stop")], seen
    )
    history: Messages = [
        {"role": "user", "content": "earlier question"},
        {"role": "assistant", "content": "earlier answer"},
    ]
    _run(
        run_agent(
            "follow-up",
            tier=TIER,
            registry=_echo_registry(),
            sink=_sink(),
            task_id="t",
            history=history,
            call_factory=factory,  # type: ignore[arg-type]
        )
    )
    msgs = seen[0]
    roles = [m.get("role") for m in msgs]
    contents = [str(m.get("content")) for m in msgs]
    assert roles == ["system", "user", "assistant", "user"]
    assert "earlier question" in contents[1]
    assert "earlier answer" in contents[2]
    assert contents[3] == "follow-up"  # this turn's task comes last


def test_context_budget_nudges_once(tmp_path: Path) -> None:
    """Once accumulated tool output passes the soft limit, the loop injects one
    convergence nudge (and only one) — soft governance, not a hard cap."""
    reg = ToolRegistry()
    reg.register(
        Tool(
            "big",
            "returns a lot",
            {"type": "object", "properties": {}},
            lambda _a: "x" * 500,
        )
    )
    big = _tool_call("c", "big", "{}")
    seen: list[Messages] = []
    factory = _recording_factory(
        [
            BackendResponse(content="", tool_calls=[big], finish_reason="tool_calls"),
            BackendResponse(content="", tool_calls=[big], finish_reason="tool_calls"),
            BackendResponse(content="done", finish_reason="stop"),
        ],
        seen,
    )
    _run(
        run_agent(
            "gather a lot",
            tier=TIER,
            registry=reg,
            sink=_sink(),
            task_id="t",
            context_soft_chars=100,
            call_factory=factory,  # type: ignore[arg-type]
        )
    )
    # The final turn's message list must contain exactly one budget nudge.
    final_messages = seen[-1]
    nudges = [
        m
        for m in final_messages
        if m.get("role") == "system" and "[context budget]" in str(m.get("content"))
    ]
    assert len(nudges) == 1


def test_backend_failure_is_soft_error() -> None:
    def factory(_schema: list[dict[str, object]]) -> Call:
        async def call(_t: Tier, _m: Messages) -> BackendResponse:
            raise BackendError("backend down")

        return call

    result = _run(
        run_agent(
            "anything",
            tier=TIER,
            registry=_echo_registry(),
            sink=_sink(),
            task_id="t",
            call_factory=factory,  # type: ignore[arg-type]
        )
    )
    assert result.stopped == "error"
    assert "unavailable" in result.final_text
