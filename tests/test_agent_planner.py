"""The cheap local prehook planner, driven offline by a scripted backend.

Proves it: strips a reasoning model's ``<think>`` scratch, returns a cleaned
plan, records the boundary, and — the load-bearing property — **fails soft** to
``None`` (the brain runs unguided) when disabled, when the model errors, or when
the answer is empty. The planner only drafts; it never blocks a run.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable
from pathlib import Path
from typing import TypeVar

import pytest
from daemon.exec import BackendError, BackendResponse, Call, Messages
from kernel.contracts import Tier
from kernel.metrics import MetricsSink
from products.agent.planner import plan_task, planner_tier

TIER = Tier.model("planner:test", where="local", backend="ollama")

_T = TypeVar("_T")


def _run(coro: Awaitable[_T]) -> _T:
    return asyncio.run(coro)  # type: ignore[arg-type]


def _sink() -> MetricsSink:
    return MetricsSink(Path("/dev/null"))


def _call(content: str, *, seen: dict[str, Messages] | None = None) -> Call:
    async def call(_tier: Tier, messages: Messages) -> BackendResponse:
        if seen is not None:
            seen["m"] = messages
        return BackendResponse(content=content, finish_reason="stop")

    return call


def _raising_call() -> Call:
    async def call(_tier: Tier, _messages: Messages) -> BackendResponse:
        raise BackendError("planner offline", retryable=True)

    return call


def test_plan_task_returns_cleaned_plan() -> None:
    # The <think> reasoning scratch is stripped; only the checklist is returned.
    plan = _run(
        plan_task(
            "build a thing",
            sink=_sink(),
            task_id="p",
            tier=TIER,
            call=_call("<think>let me think</think>\n1. edit a.py\n2. test"),
        )
    )
    assert plan == "1. edit a.py\n2. test"


def test_plan_task_sends_planner_system_prompt() -> None:
    seen: dict[str, Messages] = {}
    _run(
        plan_task(
            "do it",
            sink=_sink(),
            task_id="p",
            tier=TIER,
            call=_call("1. step", seen=seen),
        )
    )
    roles = [m["role"] for m in seen["m"]]
    assert roles == ["system", "user"]
    assert "checklist" in str(seen["m"][0]["content"]).lower()
    assert seen["m"][1]["content"] == "do it"


def test_plan_task_fail_soft_on_backend_error() -> None:
    plan = _run(
        plan_task(
            "do it", sink=_sink(), task_id="p", tier=TIER, call=_raising_call()
        )
    )
    assert plan is None  # the brain runs unguided, never blocked


def test_plan_task_empty_answer_is_none() -> None:
    # A model that emits only reasoning leaves nothing to inject.
    plan = _run(
        plan_task(
            "do it",
            sink=_sink(),
            task_id="p",
            tier=TIER,
            call=_call("<think>all thought, no plan</think>"),
        )
    )
    assert plan is None


def test_plan_task_disabled_returns_none(monkeypatch: pytest.MonkeyPatch) -> None:
    # KINOX_PLANNER=off → no planner tier → skip planning entirely (fail-soft).
    monkeypatch.setenv("KINOX_PLANNER", "off")
    plan = _run(
        plan_task("do it", sink=_sink(), task_id="p", call=_call("1. step"))
    )
    assert plan is None


def test_plan_task_records_boundary(tmp_path: Path) -> None:
    sink = MetricsSink(tmp_path / "metrics.jsonl")
    _run(
        plan_task(
            "do it", sink=sink, task_id="p", tier=TIER, call=_call("1. step")
        )
    )
    log = (tmp_path / "metrics.jsonl").read_text()
    assert "plan" in log  # the prehook is an auditable boundary (kind="plan")


def test_planner_tier_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("KINOX_PLANNER", "my-model")
    monkeypatch.setenv("KINOX_PLANNER_BACKEND", "ollama")
    tier = planner_tier()
    assert tier is not None
    assert tier.model_name == "my-model"
    assert tier.backend == "ollama"


def test_planner_tier_disabled_is_none(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("KINOX_PLANNER", "none")
    assert planner_tier() is None
