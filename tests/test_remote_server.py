"""Tests for products/remote/server.py — the network transport + auth gate (P2).

The app is exercised via FastAPI's TestClient (its client host is non-loopback,
so requests go through the bearer gate). The fail-CLOSED startup check is a pure
function, asserted without binding a socket.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from products.agent.loop import AgentResult, AgentStep
from products.remote.server import RemoteConfig, assert_bind_safe, create_remote_app

_AUTH = {"Authorization": "Bearer good"}


def _app(**kw: object) -> TestClient:
    return TestClient(create_remote_app(RemoteConfig(tokens=frozenset({"good"}), **kw)))


def test_status_requires_a_token() -> None:
    with _app() as client:
        assert client.get("/remote/status").status_code == 401


def test_status_rejects_a_bad_token() -> None:
    with _app() as client:
        r = client.get("/remote/status", headers={"Authorization": "Bearer bad"})
        assert r.status_code == 401
        assert "token" in r.json()["error"]["message"]


def test_status_accepts_a_good_token() -> None:
    with _app() as client:
        r = client.get("/remote/status", headers={"Authorization": "Bearer good"})
        assert r.status_code == 200
        body = r.json()
        assert body["remote"] == "enabled"
        assert body["paired_devices"] == 1


def test_denied_requests_are_counted() -> None:
    with _app() as client:
        client.get("/remote/status")  # no token → denied
        client.get("/remote/status", headers={"Authorization": "Bearer bad"})
        r = client.get("/remote/status", headers={"Authorization": "Bearer good"})
        assert r.json()["auth_denied"] == 2


def test_tokens_load_from_disk_on_startup(tmp_path: Path) -> None:
    (tmp_path / "phone.token").write_text("disksecret", encoding="utf-8")
    app = create_remote_app(RemoteConfig(token_dir=tmp_path))
    with TestClient(app) as client:
        assert client.get("/remote/status").status_code == 401
        r = client.get(
            "/remote/status", headers={"Authorization": "Bearer disksecret"}
        )
        assert r.status_code == 200
        assert r.json()["paired_devices"] == 1


# --- fail-CLOSED startup ----------------------------------------------------


def test_bind_safe_allows_loopback_without_token() -> None:
    assert_bind_safe("127.0.0.1", None)  # no raise
    assert_bind_safe(None, None)  # Unix-socket path


def test_bind_safe_refuses_remote_without_token(tmp_path: Path) -> None:
    with pytest.raises(RuntimeError, match="device token"):
        assert_bind_safe("0.0.0.0", tmp_path)  # noqa: S104 — empty dir, no tokens


def test_bind_safe_allows_remote_with_token(tmp_path: Path) -> None:
    (tmp_path / "d.token").write_text("secret", encoding="utf-8")
    assert_bind_safe("100.64.164.41", tmp_path)  # no raise


# --- P3: remote agent run ---------------------------------------------------


def _fake_runner(captured: list[tuple[str, list[dict[str, object]], int]]):
    """A runner that records its args and echoes a deterministic AgentResult."""

    async def run(
        task: str, history: list[dict[str, object]], spent_offset: int
    ) -> AgentResult:
        captured.append((task, list(history), spent_offset))
        return AgentResult(
            final_text=f"answer:{task}",
            steps=[
                AgentStep("tool", "read_file", "a.py"),
                AgentStep("final", "", f"answer:{task}"),
            ],
            turns=1,
            stopped="complete",
            tokens_spent=spent_offset + 100,
        )

    return run


def _run_app(**kw: object) -> TestClient:
    return TestClient(
        create_remote_app(RemoteConfig(tokens=frozenset({"good"}), **kw))
    )


def test_agent_run_requires_auth() -> None:
    with _run_app(run=_fake_runner([])) as client:
        assert client.post("/v1/agent/run", json={"task": "hi"}).status_code == 401


def test_agent_run_rejects_empty_task() -> None:
    with _run_app(run=_fake_runner([])) as client:
        r = client.post("/v1/agent/run", json={"task": "  "}, headers=_AUTH)
        assert r.status_code == 400


def test_agent_run_returns_result_and_trace() -> None:
    with _run_app(run=_fake_runner([])) as client:
        r = client.post("/v1/agent/run", json={"task": "list files"}, headers=_AUTH)
        assert r.status_code == 200
        body = r.json()
        assert body["final_text"] == "answer:list files"
        assert body["stopped"] == "complete"
        assert body["tokens_spent"] == 100
        # only tool/blocked steps are surfaced (not the "final" step)
        assert body["steps"] == [
            {"kind": "tool", "name": "read_file", "detail": "a.py"}
        ]


def test_agent_run_accrues_tokens_and_history_across_a_session() -> None:
    captured: list[tuple[str, list[dict[str, object]], int]] = []
    with _run_app(run=_fake_runner(captured)) as client:
        first = client.post(
            "/v1/agent/run", json={"task": "one", "session_id": "s1"}, headers=_AUTH
        ).json()
        second = client.post(
            "/v1/agent/run", json={"task": "two", "session_id": "s1"}, headers=_AUTH
        ).json()
    assert first["tokens_spent"] == 100
    assert second["tokens_spent"] == 200  # 100 carried in via spent_offset + 100
    # The second turn was seeded with the first turn's spend and its history.
    _, hist2, offset2 = captured[1]
    assert offset2 == 100
    assert {"role": "user", "content": "one"} in hist2


def test_agent_run_sessions_are_isolated() -> None:
    captured: list[tuple[str, list[dict[str, object]], int]] = []
    with _run_app(run=_fake_runner(captured)) as client:
        client.post(
            "/v1/agent/run", json={"task": "a", "session_id": "x"}, headers=_AUTH
        )
        other = client.post(
            "/v1/agent/run", json={"task": "b", "session_id": "y"}, headers=_AUTH
        ).json()
    assert other["tokens_spent"] == 100  # session y started fresh, not 200


def test_agent_run_is_fail_soft_on_runner_error() -> None:
    async def boom(
        task: str, history: list[dict[str, object]], spent_offset: int
    ) -> AgentResult:
        raise RuntimeError("no model available")

    with _run_app(run=boom) as client:
        r = client.post("/v1/agent/run", json={"task": "hi"}, headers=_AUTH)
        assert r.status_code == 503
        assert "no model" in r.json()["error"]["message"]
