"""Tests for daemon.server — the FastAPI broker app (TDD, M1 brick 1).

Uses FastAPI ``TestClient`` with a **stub backend** and a fixed manifest, so the
suite runs offline — no live Ollama, no Unix socket, no GPU (spec §7). The
``call`` transport and the manifest source are injected through ``BrokerConfig``
so the HTTP surface can be exercised deterministically.
"""
# fastapi's TestClient (and its httpx return types) are untyped in this env, so
# resp/.post/.json infer as unknown. That is a third-party typing gap in the
# test transport, not in daemon/ (which is pyright-clean on its own), so scope
# the unknown-type rules off for this file only.
# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false, reportUnknownArgumentType=false

from __future__ import annotations

from pathlib import Path
from typing import Any

from daemon.exec import BackendError, BackendResponse
from daemon.resources import ResourceSnapshot
from daemon.server import BrokerConfig, create_app
from fastapi.testclient import TestClient
from kernel.contracts import Tier
from kernel.manifest import LocalModel, Manifest


def _manifest(**kw: object) -> Manifest:
    base: dict[str, object] = dict(
        cpu_count=8,
        ram_gb=60.0,
        gpu_vram_gb=20.0,
        local_models=(LocalModel("small", 4.0), LocalModel("big", 18.0)),
        cloud_available=False,
    )
    base.update(kw)
    return Manifest(**base)  # type: ignore[arg-type]


def _client(config: BrokerConfig) -> TestClient:
    return TestClient(create_app(config))


def test_chat_completions_happy_path_openai_shape(tmp_path: Path) -> None:
    async def call(tier: Tier, messages: list[dict[str, str]]) -> BackendResponse:
        return BackendResponse(content="hello there", tokens_in=7, tokens_out=2)

    config = BrokerConfig(
        probe=_manifest,
        call=call,
        metrics_path=tmp_path / "events.jsonl",
    )
    client = _client(config)
    resp = client.post(
        "/v1/chat/completions",
        json={"model": "auto", "messages": [{"role": "user", "content": "hi"}]},
    )
    assert resp.status_code == 200
    body: Any = resp.json()
    body = resp.json()
    assert body["object"] == "chat.completion"
    assert body["choices"][0]["message"]["role"] == "assistant"
    assert body["choices"][0]["message"]["content"] == "hello there"
    assert body["model"] == "small"  # smallest local picked for "auto"
    assert body["usage"]["prompt_tokens"] == 7
    assert body["usage"]["completion_tokens"] == 2


def test_chat_completions_records_event(tmp_path: Path) -> None:
    async def call(tier: Tier, messages: list[dict[str, str]]) -> BackendResponse:
        return BackendResponse(content="x", tokens_in=1, tokens_out=1)

    metrics_path = tmp_path / "events.jsonl"
    config = BrokerConfig(probe=_manifest, call=call, metrics_path=metrics_path)
    _client(config).post(
        "/v1/chat/completions",
        json={"messages": [{"role": "user", "content": "hi"}]},
    )
    assert metrics_path.exists()
    lines = metrics_path.read_text().strip().splitlines()
    assert len(lines) == 1


def test_chat_completions_preferred_model_pins_tier(tmp_path: Path) -> None:
    async def call(tier: Tier, messages: list[dict[str, str]]) -> BackendResponse:
        return BackendResponse(content=tier.model_name or "", tokens_in=1, tokens_out=1)

    config = BrokerConfig(probe=_manifest, call=call, metrics_path=tmp_path / "e.jsonl")
    resp = _client(config).post(
        "/v1/chat/completions",
        json={"model": "big", "messages": [{"role": "user", "content": "hi"}]},
    )
    assert resp.json()["model"] == "big"


def test_chat_completions_exhausted_returns_503_error_object(tmp_path: Path) -> None:
    async def call(tier: Tier, messages: list[dict[str, str]]) -> BackendResponse:
        raise BackendError("everything is down", retryable=True)

    config = BrokerConfig(probe=_manifest, call=call, metrics_path=tmp_path / "e.jsonl")
    resp = _client(config).post(
        "/v1/chat/completions",
        json={"messages": [{"role": "user", "content": "hi"}]},
    )
    assert resp.status_code == 503
    body: Any = resp.json()
    body = resp.json()
    # OpenAI-shape error object, never an unhandled crash (spec §6).
    assert "error" in body
    assert body["error"]["type"] == "broker_chain_exhausted"
    assert isinstance(body["error"]["message"], str)


def test_exhausted_still_records_failure_event(tmp_path: Path) -> None:
    async def call(tier: Tier, messages: list[dict[str, str]]) -> BackendResponse:
        raise BackendError("down", retryable=True)

    metrics_path = tmp_path / "e.jsonl"
    config = BrokerConfig(probe=_manifest, call=call, metrics_path=metrics_path)
    _client(config).post(
        "/v1/chat/completions",
        json={"messages": [{"role": "user", "content": "hi"}]},
    )
    # The failure path still emits exactly one EventRecord (no silent gap).
    assert metrics_path.exists()
    assert len(metrics_path.read_text().strip().splitlines()) == 1


def test_empty_manifest_returns_503(tmp_path: Path) -> None:
    async def call(tier: Tier, messages: list[dict[str, str]]) -> BackendResponse:
        raise AssertionError("no tier should be called on an empty chain")

    config = BrokerConfig(
        probe=lambda: _manifest(local_models=()),
        call=call,
        metrics_path=tmp_path / "e.jsonl",
    )
    resp = _client(config).post(
        "/v1/chat/completions",
        json={"messages": [{"role": "user", "content": "hi"}]},
    )
    assert resp.status_code == 503


def test_route_returns_chain_without_executing(tmp_path: Path) -> None:
    called = False

    async def call(tier: Tier, messages: list[dict[str, str]]) -> BackendResponse:
        nonlocal called
        called = True
        return BackendResponse(content="x")

    config = BrokerConfig(probe=_manifest, call=call, metrics_path=tmp_path / "e.jsonl")
    resp = _client(config).get("/broker/route", params={"model": "big"})
    assert resp.status_code == 200
    body: Any = resp.json()
    body = resp.json()
    assert [t["model_name"] for t in body["chain"]] == ["big", "small"]
    assert called is False  # /broker/route never executes


def test_route_default_chain_smallest_first(tmp_path: Path) -> None:
    async def call(tier: Tier, messages: list[dict[str, str]]) -> BackendResponse:
        return BackendResponse(content="x")

    config = BrokerConfig(probe=_manifest, call=call, metrics_path=tmp_path / "e.jsonl")
    body: Any = _client(config).get("/broker/route").json()
    body = _client(config).get("/broker/route").json()
    assert [t["model_name"] for t in body["chain"]] == ["small", "big"]


def test_status_shape(tmp_path: Path) -> None:
    async def call(tier: Tier, messages: list[dict[str, str]]) -> BackendResponse:
        return BackendResponse(content="x", tokens_in=1, tokens_out=1)

    config = BrokerConfig(probe=_manifest, call=call, metrics_path=tmp_path / "e.jsonl")
    client = _client(config)
    # Drive one call so there is a recent event and a last_tier_used.
    client.post(
        "/v1/chat/completions",
        json={"messages": [{"role": "user", "content": "hi"}]},
    )
    resp = client.get("/broker/status")
    assert resp.status_code == 200
    body: Any = resp.json()
    body = resp.json()
    assert "manifest" in body
    assert body["manifest"]["gpu_vram_gb"] == 20.0
    assert body["last_tier_used"] == "model:local:small"
    assert isinstance(body["recent_events"], list)
    assert len(body["recent_events"]) == 1


def test_status_empty_when_no_events(tmp_path: Path) -> None:
    async def call(tier: Tier, messages: list[dict[str, str]]) -> BackendResponse:
        return BackendResponse(content="x")

    config = BrokerConfig(probe=_manifest, call=call, metrics_path=tmp_path / "e.jsonl")
    body: Any = _client(config).get("/broker/status").json()
    assert body["last_tier_used"] is None
    assert body["recent_events"] == []


def test_status_lists_backend_per_local_model(tmp_path: Path) -> None:
    async def call(tier: Tier, messages: list[dict[str, str]]) -> BackendResponse:
        return BackendResponse(content="x")

    config = BrokerConfig(probe=_manifest, call=call, metrics_path=tmp_path / "e.jsonl")
    body: Any = _client(config).get("/broker/status").json()
    models = body["manifest"]["local_models"]
    # Each entry carries its serving backend so the operator sees a multi-backend
    # manifest (the _manifest fixture's models default to ollama).
    assert {"name": "small", "backend": "ollama"} in models


def test_status_includes_live_resource_snapshot(tmp_path: Path) -> None:
    async def call(tier: Tier, messages: list[dict[str, str]]) -> BackendResponse:
        return BackendResponse(content="x")

    snap = ResourceSnapshot(
        vram_total_gb=24.0,
        vram_used_gb=4.0,
        cpu_percent=5.0,
        ram_used_gb=8.0,
        ram_total_gb=64.0,
    )
    config = BrokerConfig(
        probe=_manifest,
        call=call,
        metrics_path=tmp_path / "e.jsonl",
        resources=lambda: snap,
    )
    body: Any = _client(config).get("/broker/status").json()
    assert body["resources"]["vram_total_gb"] == 24.0
    assert body["resources"]["vram_free_gb"] == 20.0  # derived total - used
    body = _client(config).get("/broker/status").json()
    assert body["last_tier_used"] is None
    assert body["recent_events"] == []
