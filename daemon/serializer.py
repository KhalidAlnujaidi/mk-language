"""The single-slot inference guard (broker brick 1, spec §4.3).

Only one inference may be in flight at a time on the kinox side. This is a thin
wrapper over ``asyncio.Semaphore(1)`` that complements Ollama's
``OLLAMA_MAX_LOADED_MODELS=1``: even before a request reaches Ollama, the broker
holds a single slot so concurrent clients queue FIFO rather than thrashing the
one resident model (brick 1 is FIFO; a priority queue is deferred — spec §2).

The semaphore guarantees the slot is released even when the guarded block
raises, so a failing inference never wedges the broker.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager


class Serializer:
    """A one-at-a-time gate around model inference."""

    def __init__(self) -> None:
        self._semaphore = asyncio.Semaphore(1)

    @asynccontextmanager
    async def slot(self) -> AsyncGenerator[None]:
        """Acquire the single inference slot for the duration of the block.

        Releases the slot on exit, including when the block raises, so a failed
        inference cannot leak the slot and deadlock subsequent requests.
        """
        await self._semaphore.acquire()
        try:
            yield
        finally:
            self._semaphore.release()
