"""Tests for daemon.exec — the fallback-walking executor (TDD, M1 brick 1).

All backend I/O is injected via the ``call`` argument (spec §4.2), so the suite
runs offline with fakes — no live Ollama, no network, no GPU.
"""

from __future__ import annotations

import asyncio
from collections.abc import Coroutine
from typing import TypeVar

import pytest
from daemon.exec import (
    BackendError,
    BackendResponse,
    ChainExhausted,
    ExecResult,
    execute,
)
from kernel.contracts import EventRecord, Tier

_MESSAGES = [{"role": "user", "content": "hi"}]

_T = TypeVar("_T")


def _local(name: str) -> Tier:
    return Tier.model(name, where="local")


def _cloud(name: str) -> Tier:
    return Tier.model(name, where="cloud")


def _run(coro: Coroutine[object, object, _T]) -> _T:
    return asyncio.run(coro)


def test_success_on_first_tier() -> None:
    async def call(tier: Tier, messages: list[dict[str, str]]) -> BackendResponse:
        return BackendResponse(content="ok", tokens_in=5, tokens_out=2)

    chain = [_local("a"), _local("b")]
    result = _run(execute(chain, _MESSAGES, call=call, task_id="t1"))
    assert isinstance(result, ExecResult)
    assert result.content == "ok"
    assert result.tier_used == _local("a")


def test_event_record_shape_on_success() -> None:
    async def call(tier: Tier, messages: list[dict[str, str]]) -> BackendResponse:
        return BackendResponse(content="ok", tokens_in=5, tokens_out=2)

    result = _run(execute([_local("a")], _MESSAGES, call=call, task_id="t1"))
    ev = result.event
    assert isinstance(ev, EventRecord)
    assert ev.task_id == "t1"
    assert ev.tier == "model:local:a"
    assert ev.tokens_in == 5 and ev.tokens_out == 2
    assert ev.tokens_exact is True  # local Ollama counts are exact
    assert ev.latency_ms is not None and ev.latency_ms >= 0.0
    assert ev.correction_of is None


def test_cloud_tier_marks_tokens_inexact() -> None:
    async def call(tier: Tier, messages: list[dict[str, str]]) -> BackendResponse:
        return BackendResponse(
            content="ok", tokens_in=5, tokens_out=2, tokens_exact=False
        )

    result = _run(execute([_cloud("claude")], _MESSAGES, call=call, task_id="t1"))
    assert result.event.tokens_exact is False


def test_falls_through_on_retryable_failure() -> None:
    seen: list[str | None] = []

    async def call(tier: Tier, messages: list[dict[str, str]]) -> BackendResponse:
        seen.append(tier.model_name)
        if tier.model_name == "a":
            raise BackendError("OOM", retryable=True)
        return BackendResponse(content="ok", tokens_in=1, tokens_out=1)

    chain = [_local("a"), _local("b")]
    result = _run(execute(chain, _MESSAGES, call=call, task_id="t1"))
    assert result.tier_used == _local("b")
    assert seen == ["a", "b"]


def test_falls_through_on_timeout_then_5xx_then_succeeds() -> None:
    async def call(tier: Tier, messages: list[dict[str, str]]) -> BackendResponse:
        if tier.model_name == "a":
            raise BackendError("timeout", retryable=True)
        if tier.model_name == "b":
            raise BackendError("http 503", retryable=True)
        return BackendResponse(content="third", tokens_in=1, tokens_out=1)

    chain = [_local("a"), _local("b"), _local("c")]
    result = _run(execute(chain, _MESSAGES, call=call, task_id="t1"))
    assert result.content == "third"
    assert result.tier_used == _local("c")


def test_chain_exhausted_when_all_tiers_fail() -> None:
    async def call(tier: Tier, messages: list[dict[str, str]]) -> BackendResponse:
        raise BackendError("boom", retryable=True)

    with pytest.raises(ChainExhausted) as exc:
        _run(execute([_local("a"), _local("b")], _MESSAGES, call=call, task_id="t1"))
    # The exhaustion still carries a failure EventRecord (no silent gap, spec §6).
    ev = exc.value.event
    assert isinstance(ev, EventRecord)
    assert ev.task_id == "t1"
    assert ev.tokens_in is None and ev.tokens_out is None
    assert ev.tier == "model:local:b"  # last tier attempted


def test_empty_chain_is_exhausted_with_event() -> None:
    async def call(tier: Tier, messages: list[dict[str, str]]) -> BackendResponse:
        raise AssertionError("call must not happen on an empty chain")

    with pytest.raises(ChainExhausted) as exc:
        _run(execute([], _MESSAGES, call=call, task_id="t9"))
    assert exc.value.event.task_id == "t9"
    assert exc.value.event.tier == "none"


def test_non_retryable_error_still_falls_through_softly() -> None:
    # The broker fails SOFT: even a non-retryable error must not crash the walk;
    # it is absorbed and the next tier is tried.
    async def call(tier: Tier, messages: list[dict[str, str]]) -> BackendResponse:
        if tier.model_name == "a":
            raise BackendError("bad request", retryable=False)
        return BackendResponse(content="ok", tokens_in=1, tokens_out=1)

    chain = [_local("a"), _local("b")]
    result = _run(execute(chain, _MESSAGES, call=call, task_id="t1"))
    assert result.tier_used == _local("b")


def test_vram_delta_carried_when_provided() -> None:
    async def call(tier: Tier, messages: list[dict[str, str]]) -> BackendResponse:
        return BackendResponse(content="ok", tokens_in=1, tokens_out=1)

    def sample_vram() -> float | None:
        return 4.0

    result = _run(
        execute(
            [_local("a")], _MESSAGES, call=call, task_id="t1", sample_vram=sample_vram
        )
    )
    # Two samples 4.0 apart → delta 0.0; honest value, never fabricated.
    assert result.vram_delta_gb == 0.0


def test_vram_delta_is_none_when_unavailable() -> None:
    async def call(tier: Tier, messages: list[dict[str, str]]) -> BackendResponse:
        return BackendResponse(content="ok", tokens_in=1, tokens_out=1)

    result = _run(execute([_local("a")], _MESSAGES, call=call, task_id="t1"))
    assert result.vram_delta_gb is None  # null, never a fabricated 0
