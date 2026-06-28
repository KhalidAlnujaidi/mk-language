"""Tests for products/remote/server.py — the network transport + auth gate (P2).

The app is exercised via FastAPI's TestClient (its client host is non-loopback,
so requests go through the bearer gate). The fail-CLOSED startup check is a pure
function, asserted without binding a socket.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from products.remote.server import RemoteConfig, assert_bind_safe, create_remote_app


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
