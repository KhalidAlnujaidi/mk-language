"""Lazy broker daemon lifecycle (governed-TUI spec, Piece 1 — the backbone).

``kx`` brings the Model Control Plane broker up on demand: if the Unix socket is
absent or not accepting connections, start ``uvicorn daemon.server:app``
detached, poll readiness with a bounded timeout, and return. An already-healthy
broker → no-op. ``kx broker {status|start|stop}`` drives it explicitly and
``kx doctor`` reports its health.

Everything that touches the OS — starting the process and probing the socket —
is injectable, so the control flow is unit-testable without a real daemon.

Fail-soft (thesis #2): if the broker cannot be brought up, callers continue; the
groom ``tag`` step simply falls back to deterministic keyword tags. The framework
never blocks on the broker.

Stdlib-only by design: this module is imported by the ``kx`` entrypoint on the
hot path, so it must not pull in FastAPI/uvicorn at import time. ``daemon.server``
is referenced only as the ``"daemon.server:app"`` import string handed to uvicorn
in a child process.
"""

from __future__ import annotations

import os
import signal
import socket
import subprocess
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

#: Where the broker's runtime files live (socket, pidfile, log).
STATE_DIR: Path = Path.home() / ".kinox"

#: Probe a Unix socket → True iff a broker answers there. Injectable in tests.
HealthCheck = Callable[[Path], bool]
#: Start the broker bound to a socket. Injectable so no real uvicorn in tests.
Starter = Callable[[Path], None]


def socket_path() -> Path:
    """The broker's Unix socket. ``KINOX_BROKER_SOCKET`` overrides the default.

    The default lives under ``~/.kinox`` (userspace, always writable) rather than
    ``/run`` so no root step is needed for a single-user local-first workspace.
    """
    return Path(os.environ.get("KINOX_BROKER_SOCKET", str(STATE_DIR / "broker.sock")))


def pid_path() -> Path:
    return STATE_DIR / "broker.pid"


def log_path() -> Path:
    return STATE_DIR / "broker.log"


@dataclass(frozen=True)
class BrokerState:
    """The outcome of an ensure-up call (also what ``kx broker`` prints)."""

    running: bool
    socket: Path
    #: True only when THIS call started the daemon (vs. it already being up).
    started: bool
    reason: str


def probe(sock: Path, *, timeout: float = 0.5) -> bool:
    """True if a broker is accepting connections on *sock* and returns 200.

    Speaks the minimum HTTP/1.0 needed to hit ``/broker/status`` over the Unix
    socket. Any error (missing socket, refused, timeout, garbage) → ``False``.
    """
    if not sock.exists():
        return False
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as conn:
            conn.settimeout(timeout)
            conn.connect(str(sock))
            conn.sendall(b"GET /broker/status HTTP/1.0\r\nHost: kinox\r\n\r\n")
            head = conn.recv(32)
    except OSError:
        return False
    return head.startswith(b"HTTP/") and b"200" in head[:20]


def _default_start(sock: Path) -> None:
    """Start ``uvicorn daemon.server:app`` detached, bound to *sock*.

    The child gets its own session (so it survives the launching shell) and the
    same ``KINOX_BROKER_SOCKET`` the parent computed, so server and clients agree
    on the path. Its stdout/stderr stream to ``~/.kinox/broker.log``.
    """
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    sock.parent.mkdir(parents=True, exist_ok=True)
    repo_root = Path(__file__).resolve().parent.parent
    env = dict(os.environ)
    env["KINOX_BROKER_SOCKET"] = str(sock)
    with open(log_path(), "ab") as log:
        proc = subprocess.Popen(  # noqa: S603 — fixed argv, no shell
            [sys.executable, "-m", "uvicorn", "daemon.server:app", "--uds", str(sock)],
            cwd=str(repo_root),
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=log,
            stderr=log,
            start_new_session=True,
        )
    pid_path().write_text(str(proc.pid), encoding="utf-8")


def ensure_up(
    *,
    sock: Path | None = None,
    start: Starter = _default_start,
    is_healthy: HealthCheck = probe,
    attempts: int = 30,
    delay: float = 0.1,
) -> BrokerState:
    """Make the broker live, lazily. No-op if already healthy.

    Healthy now → ``BrokerState(running=True, started=False)``. Otherwise *start*
    it and poll *is_healthy* up to *attempts* times (``delay`` s apart). Any
    failure to start, or a daemon that never becomes ready, returns
    ``running=False`` — the caller fails soft.
    """
    target = sock if sock is not None else socket_path()
    if is_healthy(target):
        return BrokerState(True, target, False, "already running")
    try:
        start(target)
    except Exception as exc:  # noqa: BLE001 — fail soft on any start failure
        return BrokerState(False, target, False, f"start failed: {exc}")
    for _ in range(attempts):
        if is_healthy(target):
            return BrokerState(True, target, True, "started")
        time.sleep(delay)
    return BrokerState(False, target, True, "started but not ready in time")


def stop(
    *,
    sock: Path | None = None,
    pidfile: Path | None = None,
    is_healthy: HealthCheck = probe,
) -> str:
    """Stop a kx-started broker via its pidfile; clean up the socket.

    A broker running without our pidfile (started outside ``kx``) is left alone.
    """
    target = sock if sock is not None else socket_path()
    pf = pidfile if pidfile is not None else pid_path()
    if not pf.exists():
        if is_healthy(target):
            return "broker running but not started by kx (no pidfile) — left alone"
        return "broker not running"
    try:
        pid = int(pf.read_text(encoding="utf-8").strip())
        os.kill(pid, signal.SIGTERM)
        msg = f"stopped broker (pid {pid})"
    except (ValueError, ProcessLookupError, OSError) as exc:
        msg = f"broker not running ({exc})"
    pf.unlink(missing_ok=True)
    target.unlink(missing_ok=True)
    return msg


def status_line(*, sock: Path | None = None, is_healthy: HealthCheck = probe) -> str:
    """One-line health summary for ``kx broker status`` and ``kx doctor``."""
    target = sock if sock is not None else socket_path()
    state = "up" if is_healthy(target) else "down"
    return f"broker: {state}  ({target})"
