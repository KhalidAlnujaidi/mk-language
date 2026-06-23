"""Tests for products/groom/model_tag.py — broker-backed fuzzy tagging.

The tag step is the ONE fuzzy groom stage; ``broker_tag`` runs it on a local
model through the broker dispatch (offloading cheap classification off the cloud)
and parses the reply into valid tags. SOFT fail-direction: any backend error,
empty reply, or reply with no valid tags returns ``None`` so the caller falls
back to keyword tags. The async broker boundary is injected (``call``) so the
suite runs offline.
"""

from __future__ import annotations

import httpx
from daemon.backends import BackendSpec, make_dispatch
from daemon.exec import BackendResponse, Call
from kernel.contracts import Tier
from products.groom.model_tag import broker_tag

_TIER = Tier.model("qwen3:1.7b", where="local", backend="ollama")


def _call_returning(content: str) -> Call:
    async def call(tier: Tier, messages: list[dict[str, str]]) -> BackendResponse:
        return BackendResponse(content=content)

    return call


def test_broker_tag_parses_model_reply() -> None:
    mt = broker_tag(call=_call_returning("bug, feature"))
    assert mt(_TIER, "fix the thing and add a button") == ("bug", "feature")


def test_broker_tag_filters_to_valid_tags() -> None:
    # Hallucinated/out-of-vocabulary tags are dropped; valid ones kept in order.
    mt = broker_tag(call=_call_returning("bug, banana, test, nonsense"))
    assert mt(_TIER, "x") == ("bug", "test")


def test_broker_tag_empty_reply_returns_none() -> None:
    assert broker_tag(call=_call_returning(""))(_TIER, "x") is None


def test_broker_tag_no_valid_tags_returns_none() -> None:
    assert broker_tag(call=_call_returning("hello there world"))(_TIER, "x") is None


def test_broker_tag_backend_error_returns_none() -> None:
    async def call(tier: Tier, messages: list[dict[str, str]]) -> BackendResponse:
        raise RuntimeError("backend down")  # any failure → soft None

    assert broker_tag(call=call)(_TIER, "x") is None


def test_broker_tag_end_to_end_via_dispatch() -> None:
    # Full path: broker_tag -> make_dispatch -> httpx (MockTransport), no network.
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": "refactor"}}],
                "usage": {"prompt_tokens": 9, "completion_tokens": 1},
            },
        )

    call = make_dispatch(
        {"ollama": BackendSpec("http://o/v1")},
        transport=httpx.MockTransport(handler),
    )
    assert broker_tag(call=call)(_TIER, "restructure this module") == ("refactor",)
