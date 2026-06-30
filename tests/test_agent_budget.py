"""Tests for products/agent/budget.py and the loop's token-budget early exit.

The budget policy is pure; the loop test drives run_agent with a scripted backend
that reports token usage, so a tight budget triggers the fail-soft early exit
(vision §9) offline.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable
from pathlib import Path
from typing import TypeVar

import pytest
from daemon.exec import BackendResponse, Call, Messages
from kernel.contracts import Tier
from kernel.metrics import MetricsSink
from products.agent.budget import TokenBudget
from products.agent.loop import run_agent
from products.agent.tools import Tool, ToolRegistry

_T = TypeVar("_T")
TIER = Tier.model("gemma-agentic:32k", where="local", backend="ollama")


def _run(coro: Awaitable[_T]) -> _T:
    return asyncio.run(coro)  # type: ignore[arg-type]


# --- pure policy ------------------------------------------------------------


def test_unlimited_budget_is_never_exhausted() -> None:
    b = TokenBudget(limit=None)
    assert b.exhausted(10**9) is False
    assert b.remaining(123) is None


def test_exhausted_and_remaining() -> None:
    b = TokenBudget(limit=100)
    assert b.exhausted(99) is False
    assert b.exhausted(100) is True
    assert b.exhausted(101) is True
    assert b.remaining(40) == 60
    assert b.remaining(140) == 0  # clamped, never negative


def test_negative_limit_rejected() -> None:
    with pytest.raises(ValueError):
        TokenBudget(limit=-1)


# --- loop integration -------------------------------------------------------


def _tool_call(call_id: str) -> dict[str, object]:
    return {
        "id": call_id,
        "type": "function",
        "function": {"name": "echo", "arguments": '{"x": "hi"}'},
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


def _always_tool_factory(tokens_per_turn: int) -> object:
    """A backend that every turn requests one tool call and reports usage, so the
    run would loop to max_turns if the budget did not stop it first."""

    def factory(_schema: list[dict[str, object]]) -> Call:
        async def call(_tier: Tier, _messages: Messages) -> BackendResponse:
            return BackendResponse(
                content="",
                tokens_in=tokens_per_turn,
                tokens_out=0,
                tool_calls=[_tool_call("c1")],
                finish_reason="tool_calls",
            )

        return call

    return factory


def test_loop_stops_on_token_budget() -> None:
    result = _run(
        run_agent(
            "do the thing",
            tier=TIER,
            registry=_echo_registry(),
            sink=MetricsSink(Path("/dev/null")),
            task_id="t",
            max_turns=50,  # high — the budget, not turns, must stop the run
            stall_repeats=100,  # disable the convergence gate; isolate the budget
            token_budget=TokenBudget(limit=250),
            call_factory=_always_tool_factory(tokens_per_turn=100),  # type: ignore[arg-type]
        )
    )
    assert result.stopped == "budget"
    # 100 tokens/turn, limit 250 → turns 0,1,2 run (spent 0→100→200), turn 3 top
    # sees spent=300 >= 250 and stops. So 3 completed turns.
    assert result.turns == 3
    assert "budget" in result.final_text


def test_no_budget_runs_to_max_turns() -> None:
    result = _run(
        run_agent(
            "do the thing",
            tier=TIER,
            registry=_echo_registry(),
            sink=MetricsSink(Path("/dev/null")),
            task_id="t",
            max_turns=4,
            stall_repeats=100,  # disable the convergence gate; isolate max_turns
            self_heal=False,
            call_factory=_always_tool_factory(tokens_per_turn=100),  # type: ignore[arg-type]
        )
    )
    assert result.stopped == "max_turns"
    assert result.turns == 4


# --- continuation accrual (per-session budget across runs) ------------------


def test_result_reports_cumulative_tokens_spent() -> None:
    result = _run(
        run_agent(
            "do the thing",
            tier=TIER,
            registry=_echo_registry(),
            sink=MetricsSink(Path("/dev/null")),
            task_id="t",
            max_turns=3,
            stall_repeats=100,
            self_heal=False,
            call_factory=_always_tool_factory(tokens_per_turn=100),  # type: ignore[arg-type]
        )
    )
    # 3 turns × 100 tok each, summed and returned for the caller to carry forward.
    assert result.tokens_spent == 300


def test_spent_offset_seeds_the_tally_and_carries_across_runs() -> None:
    # A fresh run starting already-spent from a prior turn keeps accruing on top.
    result = _run(
        run_agent(
            "do the thing",
            tier=TIER,
            registry=_echo_registry(),
            sink=MetricsSink(Path("/dev/null")),
            task_id="t",
            max_turns=2,
            stall_repeats=100,
            spent_offset=500,
            self_heal=False,
            call_factory=_always_tool_factory(tokens_per_turn=100),  # type: ignore[arg-type]
        )
    )
    assert result.tokens_spent == 700  # 500 carried in + 2×100 this run


def test_session_budget_stops_a_later_run_via_offset() -> None:
    # The budget governs the SESSION: with 240 already spent and a 250 ceiling,
    # the next run stops almost immediately — the offset alone nearly exhausts it.
    result = _run(
        run_agent(
            "do the thing",
            tier=TIER,
            registry=_echo_registry(),
            sink=MetricsSink(Path("/dev/null")),
            task_id="t",
            max_turns=50,
            stall_repeats=100,
            token_budget=TokenBudget(limit=250),
            spent_offset=240,
            call_factory=_always_tool_factory(tokens_per_turn=100),  # type: ignore[arg-type]
        )
    )
    # Turn 0 runs (240→340), turn 1 top sees 340 ≥ 250 → stop. 1 completed turn.
    assert result.stopped == "budget"
    assert result.turns == 1
    assert result.tokens_spent == 340


def test_agent_resumes_from_state() -> None:
    # First run stops at budget
    run1 = _run(
        run_agent(
            "do the thing",
            tier=TIER,
            registry=_echo_registry(),
            sink=MetricsSink(Path("/dev/null")),
            task_id="t",
            max_turns=50,
            stall_repeats=100,
            token_budget=TokenBudget(limit=150),
            call_factory=_always_tool_factory(tokens_per_turn=100),  # type: ignore[arg-type]
        )
    )
    assert run1.stopped == "budget"
    assert run1.turns == 2
    assert run1.tokens_spent == 200
    assert run1.state is not None

    # Second run resumes with larger budget
    run2 = _run(
        run_agent(
            "do the thing",
            tier=TIER,
            registry=_echo_registry(),
            sink=MetricsSink(Path("/dev/null")),
            task_id="t",
            max_turns=50,
            stall_repeats=100,
            token_budget=TokenBudget(limit=450),
            resume_from=run1.state,
            call_factory=_always_tool_factory(tokens_per_turn=100),  # type: ignore[arg-type]
        )
    )
    assert run2.stopped == "budget"
    # Should start from turn 2 and do 3 more turns (to hit 500 > 450 limit)
    assert run2.turns == 5
    assert run2.tokens_spent == 500
