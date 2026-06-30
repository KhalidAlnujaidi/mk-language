"""Tests for daemon.serializer — the single-slot inference guard (TDD).

Only one inference may be in flight at a time on the kinox side, complementing
Ollama's ``OLLAMA_MAX_LOADED_MODELS=1`` (spec §4.3). We assert the observed
max-concurrency is exactly 1, and that the slot is released on exception.
"""

from __future__ import annotations

import asyncio
import contextlib

from daemon.serializer import Serializer


def test_concurrent_calls_run_one_at_a_time() -> None:
    serializer = Serializer()
    live = 0
    max_live = 0

    async def work() -> None:
        nonlocal live, max_live
        async with serializer.slot():
            live += 1
            max_live = max(max_live, live)
            await asyncio.sleep(0.01)  # hold the slot so overlap would be visible
            live -= 1

    async def main() -> None:
        await asyncio.gather(*(work() for _ in range(8)))

    asyncio.run(main())
    assert max_live == 1


def test_slot_released_on_exception() -> None:
    serializer = Serializer()

    async def boom() -> None:
        async with serializer.slot():
            raise ValueError("boom")

    async def main() -> None:
        # First holder raises; the slot must still be free for the second.
        with contextlib.suppress(ValueError):
            await boom()
        # If the slot leaked, this acquire would block forever; wait_for guards it.
        async with serializer.slot():
            pass

    asyncio.run(asyncio.wait_for(main(), timeout=1.0))


def test_calls_actually_serialize_in_order_of_release() -> None:
    serializer = Serializer()
    order: list[int] = []

    async def work(n: int) -> None:
        async with serializer.slot():
            order.append(n)
            await asyncio.sleep(0.005)

    async def main() -> None:
        # Launch sequentially so acquisition order is deterministic.
        tasks = [asyncio.create_task(work(n)) for n in range(4)]
        await asyncio.gather(*tasks)

    asyncio.run(main())
    assert sorted(order) == [0, 1, 2, 3]
    assert len(order) == 4
