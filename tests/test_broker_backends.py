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
    cloud_backend_specs,
    default_specs,
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
    # Anthropic speaks a different protocol and has no spec — still fails soft.
    dispatch = make_dispatch()  # default table: local + OpenAI-compatible cloud
    tier = Tier.model("claude-haiku-4-5", where="cloud", backend="anthropic")
    with pytest.raises(BackendError):
        _run(dispatch(tier, []))


# --- The cloud (OpenAI-compatible) backends -----------------------------------


def _zai_tier() -> Tier:
    return Tier.model("glm-5.2", where="cloud", backend="zai")


def test_cloud_specs_has_zai_inexact_with_auth_env() -> None:
    spec = cloud_backend_specs()["zai"]
    # The GLM Coding Plan endpoint (not the standard /api/paas/v4 API).
    assert spec.base_url == "https://api.z.ai/api/coding/paas/v4"
    assert spec.exact is False  # cloud counts are estimates, never claimed exact
    assert spec.auth_env == "ZAI_API_KEY"


def test_cloud_spec_url_env_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("KINOX_ZAI_URL", "http://proxy.test/v1")
    assert cloud_backend_specs()["zai"].base_url == "http://proxy.test/v1"


def test_cloud_specs_has_openrouter() -> None:
    spec = cloud_backend_specs()["openrouter"]
    assert spec.base_url == "https://openrouter.ai/api/v1"
    assert spec.exact is False
    assert spec.auth_env == "OPENROUTER_API_KEY"


def test_default_specs_merges_local_and_cloud() -> None:
    specs = default_specs()
    assert {"ollama", "vllm", "llamacpp", "zai", "openrouter"} <= set(specs)
    assert specs["zai"].auth_env == "ZAI_API_KEY"
    assert specs["openrouter"].auth_env == "OPENROUTER_API_KEY"


def test_generic_client_sends_bearer_when_token_given() -> None:
    captured: list[httpx.Request] = []
    transport = httpx.MockTransport(_ok_handler(captured))
    _run(
        openai_compatible_call(
            "http://x/v1", _zai_tier(), [], transport=transport, auth_token="sk-abc"
        )
    )
    assert captured[0].headers["Authorization"] == "Bearer sk-abc"


def test_generic_client_omits_auth_when_no_token() -> None:
    captured: list[httpx.Request] = []
    transport = httpx.MockTransport(_ok_handler(captured))
    _run(
        openai_compatible_call("http://x/v1", _tier("ollama"), [], transport=transport)
    )
    assert "Authorization" not in captured[0].headers


def test_dispatch_zai_routes_and_authenticates(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ZAI_API_KEY", "sk-live")
    captured: list[httpx.Request] = []
    transport = httpx.MockTransport(_ok_handler(captured))
    dispatch = make_dispatch(transport=transport)  # default table includes zai
    resp = _run(dispatch(_zai_tier(), []))
    expected = "https://api.z.ai/api/coding/paas/v4/chat/completions"
    assert str(captured[0].url) == expected
    assert captured[0].headers["Authorization"] == "Bearer sk-live"
    assert resp.tokens_exact is False  # cloud counts stay labelled inexact


def test_dispatch_zai_without_key_sends_no_auth(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("ZAI_API_KEY", raising=False)
    captured: list[httpx.Request] = []
    transport = httpx.MockTransport(_ok_handler(captured))
    dispatch = make_dispatch(transport=transport)
    _run(dispatch(_zai_tier(), []))
    # No key → no header (the real backend would 401 → executor falls through).
    assert "Authorization" not in captured[0].headers
