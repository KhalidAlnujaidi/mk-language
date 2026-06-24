"""Tests for daemon.launch — the lazy broker lifecycle (no real daemon).

Every OS-touching seam (start, health probe) is injected, so these are pure
control-flow tests: no uvicorn, no real socket.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from daemon.launch import (
    BrokerState,
    ensure_up,
    probe,
    socket_path,
    status_line,
    stop,
)


def test_socket_path_honours_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("KINOX_BROKER_SOCKET", "/tmp/custom-kinox.sock")
    assert socket_path() == Path("/tmp/custom-kinox.sock")


def test_ensure_up_is_noop_when_already_healthy(tmp_path: Path) -> None:
    started: list[Path] = []
    state = ensure_up(
        sock=tmp_path / "b.sock",
        start=lambda s: started.append(s),
        is_healthy=lambda _s: True,
    )
    assert state == BrokerState(True, tmp_path / "b.sock", False, "already running")
    assert started == []  # never started — it was already up


def test_ensure_up_starts_when_down_then_ready(tmp_path: Path) -> None:
    sock = tmp_path / "b.sock"
    started: list[Path] = []
    # Down on the first probe (before start), up afterwards.
    health = iter([False, True])

    state = ensure_up(
        sock=sock,
        start=lambda s: started.append(s),
        is_healthy=lambda _s: next(health),
        attempts=5,
        delay=0.0,
    )
    assert state.running is True
    assert state.started is True
    assert started == [sock]


def test_ensure_up_start_failure_fails_soft(tmp_path: Path) -> None:
    def boom(_s: Path) -> None:
        raise OSError("no uvicorn")

    state = ensure_up(
        sock=tmp_path / "b.sock", start=boom, is_healthy=lambda _s: False
    )
    assert state.running is False
    assert state.started is False
    assert "start failed" in state.reason


def test_ensure_up_never_ready_reports_failure(tmp_path: Path) -> None:
    state = ensure_up(
        sock=tmp_path / "b.sock",
        start=lambda _s: None,
        is_healthy=lambda _s: False,
        attempts=3,
        delay=0.0,
    )
    assert state.running is False
    assert state.started is True
    assert "not ready" in state.reason


def test_probe_false_when_socket_absent(tmp_path: Path) -> None:
    assert probe(tmp_path / "nope.sock") is False


def test_stop_when_not_running(tmp_path: Path) -> None:
    msg = stop(
        sock=tmp_path / "b.sock",
        pidfile=tmp_path / "b.pid",
        is_healthy=lambda _s: False,
    )
    assert msg == "broker not running"


def test_stop_with_bogus_pidfile_cleans_up(tmp_path: Path) -> None:
    sock = tmp_path / "b.sock"
    sock.write_bytes(b"")  # stale socket file
    pidfile = tmp_path / "b.pid"
    pidfile.write_text("not-a-pid", encoding="utf-8")

    msg = stop(sock=sock, pidfile=pidfile, is_healthy=lambda _s: False)
    assert "not running" in msg
    assert not pidfile.exists()  # cleaned up
    assert not sock.exists()


def test_stop_leaves_foreign_broker_alone(tmp_path: Path) -> None:
    msg = stop(
        sock=tmp_path / "b.sock",
        pidfile=tmp_path / "absent.pid",
        is_healthy=lambda _s: True,  # someone else's broker is up
    )
    assert "left alone" in msg


def test_status_line_reports_up_and_down(tmp_path: Path) -> None:
    up = status_line(sock=tmp_path / "b.sock", is_healthy=lambda _s: True)
    down = status_line(sock=tmp_path / "b.sock", is_healthy=lambda _s: False)
    assert "up" in up
    assert "down" in down
