"""Tests for daemon.backends — the multi-backend adapter layer (G3-2).

All local backends (Ollama, vLLM, llama.cpp) speak the same OpenAI-compatible
``/v1/chat/completions`` protocol, so there is ONE generic transport
(``openai_compatible_call``) parameterised by base URL, plus a ``dispatch`` that
selects the backend by ``tier.backend``. Cloud/unknown backends fail soft so the
executor falls through rather than misrouting.

The real httpx transport is exercised offline via ``httpx.MockTransport`` — no
network, no live server. Async calls run through ``_run`` (asyncio.run), matching
``test_broker_exec.py``.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import TypeVar

import httpx
import pytest
from daemon.backends import (
    BackendSpec,
    backend_specs,
    make_dispatch,
    openai_compatible_call,
)
from daemon.exec import BackendError
from kernel.contracts import Tier

_T = TypeVar("_T")


def _run(awaitable: Awaitable[_T]) -> _T:
    """Run any awaitable to completion (dispatch returns an ``Awaitable``, not a
    bare coroutine, so wrap it for ``asyncio.run``)."""

    async def _wrap() -> _T:
        return await awaitable

    return asyncio.run(_wrap())


def _ok_handler(
    captured: list[httpx.Request] | None = None,
) -> Callable[[httpx.Request], httpx.Response]:
    """A MockTransport handler returning a valid OpenAI-shape completion.

    When *captured* is supplied, each inbound request is appended to it so a test
    can assert which base URL was hit.
    """

    def handler(request: httpx.Request) -> httpx.Response:
        if captured is not None:
            captured.append(request)
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"role": "assistant", "content": "hi"}}],
                "usage": {"prompt_tokens": 5, "completion_tokens": 2},
            },
        )

    return handler


def _tier(backend: str) -> Tier:
    return Tier.model("m", where="local", backend=backend)


# --- The generic OpenAI-compatible client ------------------------------------


def test_generic_client_maps_content_and_usage() -> None:
    transport = httpx.MockTransport(_ok_handler())
    resp = _run(
        openai_compatible_call(
            "http://x.test/v1",
            _tier("vllm"),
            [{"role": "user", "content": "yo"}],
            exact=True,
            transport=transport,
        )
    )
    assert resp.content == "hi"
    assert resp.tokens_in == 5
    assert resp.tokens_out == 2
    assert resp.tokens_exact is True


def test_generic_client_hits_the_configured_base_url() -> None:
    captured: list[httpx.Request] = []
    transport = httpx.MockTransport(_ok_handler(captured))
    _run(
        openai_compatible_call(
            "http://my-backend.test/v1", _tier("vllm"), [], transport=transport
        )
    )
    assert str(captured[0].url) == "http://my-backend.test/v1/chat/completions"


def test_generic_client_5xx_raises_retryable() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(503, text="overloaded")

    transport = httpx.MockTransport(handler)
    with pytest.raises(BackendError) as ei:
        _run(
            openai_compatible_call(
                "http://x/v1", _tier("vllm"), [], transport=transport
            )
        )
    assert ei.value.retryable is True


def test_generic_client_transport_error_raises() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused")

    transport = httpx.MockTransport(handler)
    with pytest.raises(BackendError):
        _run(
            openai_compatible_call(
                "http://x/v1", _tier("vllm"), [], transport=transport
            )
        )


def test_generic_client_no_choices_raises() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"choices": []})

    transport = httpx.MockTransport(handler)
    with pytest.raises(BackendError):
        _run(
            openai_compatible_call(
                "http://x/v1", _tier("vllm"), [], transport=transport
            )
        )


# --- The backend spec table ---------------------------------------------------


def test_backend_specs_has_the_three_local_backends() -> None:
    specs = backend_specs()
    assert set(specs) == {"ollama", "vllm", "llamacpp"}
    assert specs["ollama"].base_url.endswith(":11434/v1")
    assert specs["vllm"].base_url.endswith(":8000/v1")
    assert specs["llamacpp"].base_url.endswith(":8080/v1")


def test_backend_specs_env_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("KINOX_VLLM_URL", "http://gpu-box:9000/v1")
    assert backend_specs()["vllm"].base_url == "http://gpu-box:9000/v1"


# --- The dispatcher -----------------------------------------------------------


def test_dispatch_routes_to_the_tiers_backend() -> None:
    captured: list[httpx.Request] = []
    transport = httpx.MockTransport(_ok_handler(captured))
    specs = {
        "ollama": BackendSpec("http://ollama.test/v1"),
        "vllm": BackendSpec("http://vllm.test/v1"),
    }
    dispatch = make_dispatch(specs, transport=transport)
    _run(dispatch(_tier("vllm"), []))
    assert str(captured[0].url) == "http://vllm.test/v1/chat/completions"


def test_dispatch_unknown_backend_fails_soft() -> None:
    dispatch = make_dispatch({"ollama": BackendSpec("http://o/v1")})
    with pytest.raises(BackendError) as ei:
        _run(dispatch(_tier("mystery"), []))
    assert ei.value.retryable is True


def test_dispatch_cloud_anthropic_fails_soft() -> None:
    # Cloud is a different protocol — explicitly out of scope this increment.
    dispatch = make_dispatch()  # default table: local backends only
    tier = Tier.model("claude-haiku-4-5", where="cloud", backend="anthropic")
    with pytest.raises(BackendError):
        _run(dispatch(tier, []))
