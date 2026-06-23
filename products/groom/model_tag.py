"""Broker-backed fuzzy tagging — offload the ONE fuzzy groom step to a local model.

``broker_tag`` builds a ``ModelTag`` (the seam injected into ``tag.tag``) that runs
a tiny classification prompt through the broker dispatch against a *local* model
(Ollama / vLLM / llama.cpp), keeping cheap intent-tagging off the cloud. The reply
is parsed into the project's valid tag vocabulary.

SOFT fail-direction (thesis #2): any backend error, timeout, empty reply, or reply
with no valid tags returns ``None`` so ``tag.tag`` falls back to keyword tags. The
groom pipeline is synchronous, so the async broker call is wrapped in
``asyncio.run`` here at the boundary.

This is the one place a *product* reaches into the *daemon* (in-process dispatch);
the kernel stays pure and the daemon never reaches back (test_architecture.py).
"""

from __future__ import annotations

import asyncio
import re

from daemon.backends import make_dispatch
from daemon.exec import BackendResponse, Call, Messages
from kernel.contracts import Tier

from products.groom.tag import VALID_TAGS, ModelTag

# Default per-call ceiling for the fuzzy tag offload (seconds). A small local
# model classifying a prompt is fast; if it isn't, we fall soft to keywords.
_DEFAULT_TIMEOUT_S = 5.0

_SYSTEM = (
    "You label a software request with 1-4 short tags from this exact set: "
    + ", ".join(sorted(VALID_TAGS))
    + ". Reply with ONLY the tags, comma-separated, nothing else."
)

# Split a model reply on commas/whitespace so "bug, feature" and "bug feature"
# both parse.
_SPLIT = re.compile(r"[,\s]+")


def _parse_tags(content: str) -> tuple[str, ...] | None:
    """Parse a model reply into valid tags (order-preserving, deduped).

    Returns ``None`` when nothing in the reply maps to a known tag, so the caller
    falls soft to keyword tags rather than trusting an empty/garbage answer.
    """
    seen: set[str] = set()
    tags: list[str] = []
    for token in _SPLIT.split(content.strip().lower()):
        if token in VALID_TAGS and token not in seen:
            seen.add(token)
            tags.append(token)
    return tuple(tags) if tags else None


def broker_tag(
    call: Call | None = None, *, timeout: float = _DEFAULT_TIMEOUT_S
) -> ModelTag:
    """Build a ``ModelTag`` that classifies via the broker dispatch.

    *call* is the async backend dispatch (defaults to a fresh ``make_dispatch``
    over the configured local backends); injected in tests. The returned callable
    is synchronous (the pipeline is), failing soft to ``None`` on any error.
    """
    dispatch: Call = call if call is not None else make_dispatch(timeout=timeout)

    def _tag(tier: Tier, text: str) -> tuple[str, ...] | None:
        messages: Messages = [
            {"role": "system", "content": _SYSTEM},
            {"role": "user", "content": text},
        ]

        async def _invoke() -> BackendResponse:
            # dispatch is typed as returning Awaitable; wrap so asyncio.run gets a
            # concrete coroutine and the result type is known.
            return await dispatch(tier, messages)

        try:
            response = asyncio.run(_invoke())
        except Exception:
            return None  # SOFT: any backend/timeout failure → fall back to keywords
        return _parse_tags(response.content)

    return _tag
