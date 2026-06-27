"""Tests for the executor's retry-with-backoff (CodeWhale Tier-2).

All backend I/O and the backoff sleep are injected, so the suite is offline and
no real time passes.
"""

from __future__ import annotations

import asyncio
from collections.abc import Coroutine
from typing import TypeVar

import pytest
from daemon.backoff import RetryPolicy
from daemon.exec import BackendError, BackendResponse, ChainExhausted, execute
from kernel.contracts import Tier

_MESSAGES = [{"role": "user", "content": "hi"}]
_T = TypeVar("_T")


def _local(name: str) -> Tier:
    return Tier.model(name, where="local")


def _run(coro: Coroutine[object, object, _T]) -> _T:
    return asyncio.run(coro)


def _recording_sleep() -> tuple[list[float], object]:
    waits: list[float] = []

    async def sleep(seconds: float) -> None:
        waits.append(seconds)

    return waits, sleep


def test_retry_succeeds_on_same_tier_after_transient_blips() -> None:
    calls = {"n": 0}

    async def call(tier: Tier, messages: list[dict[str, str]]) -> BackendResponse:
        calls["n"] += 1
        if calls["n"] < 3:
            raise BackendError("503", retryable=True)
        return BackendResponse(content="ok", tokens_in=1, tokens_out=1)

    waits, sleep = _recording_sleep()
    policy = RetryPolicy(max_attempts=3, base_delay_s=0.5, factor=2.0)
    # A single-tier chain: without retry this would exhaust; with retry it rides
    # out the two blips and stays on the SAME tier.
    result = _run(
        execute(
            [_local("a")], _MESSAGES, call=call, task_id="t",
            retry=policy, sleep=sleep,  # type: ignore[arg-type]
        )
    )
    assert result.content == "ok"
    assert result.tier_used.model_name == "a"
    assert calls["n"] == 3
    assert waits == [0.5, 1.0]  # backoff before attempts 2 and 3


def test_non_retryable_error_is_not_retried() -> None:
    calls = {"n": 0}

    async def call(tier: Tier, messages: list[dict[str, str]]) -> BackendResponse:
        calls["n"] += 1
        if tier.model_name == "a":
            raise BackendError("bad request", retryable=False)
        return BackendResponse(content="b-ok", tokens_in=1, tokens_out=1)

    waits, sleep = _recording_sleep()
    result = _run(
        execute(
            [_local("a"), _local("b")], _MESSAGES, call=call, task_id="t",
            retry=RetryPolicy(max_attempts=5), sleep=sleep,  # type: ignore[arg-type]
        )
    )
    # Tier 'a' hit once (no retry on a hard error), then fell through to 'b'.
    assert result.content == "b-ok"
    assert calls["n"] == 2
    assert waits == []


def test_exhausting_retries_falls_through_to_next_tier() -> None:
    async def call(tier: Tier, messages: list[dict[str, str]]) -> BackendResponse:
        if tier.model_name == "a":
            raise BackendError("always 503", retryable=True)
        return BackendResponse(content="b-ok", tokens_in=1, tokens_out=1)

    waits, sleep = _recording_sleep()
    result = _run(
        execute(
            [_local("a"), _local("b")], _MESSAGES, call=call, task_id="t",
            retry=RetryPolicy(max_attempts=3), sleep=sleep,  # type: ignore[arg-type]
        )
    )
    assert result.content == "b-ok"
    assert len(waits) == 2  # two backoffs on 'a' before giving up, then 'b'


def test_default_no_retry_is_legacy_one_shot() -> None:
    calls = {"n": 0}

    async def call(tier: Tier, messages: list[dict[str, str]]) -> BackendResponse:
        calls["n"] += 1
        raise BackendError("503", retryable=True)

    # No retry policy → one attempt per tier, then chain exhausted (unchanged).
    with pytest.raises(ChainExhausted):
        _run(execute([_local("a")], _MESSAGES, call=call, task_id="t"))
    assert calls["n"] == 1
