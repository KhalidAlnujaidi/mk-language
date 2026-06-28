"""The network transport for remote control (P2): bind + bearer-token gate.

A thin FastAPI app whose every network request passes the :mod:`daemon.remote_auth`
gate before anything else runs. The broker (``daemon/server.py``) is untouched and
stays local; this is the separate, authenticated surface reachable over the
tailnet. P2 ships the transport, the auth middleware, and ``/remote/status``; the
agent-run endpoints (P3/P4) mount onto this same app.

Two fail-CLOSED guarantees (thesis #2):
- a network request without a valid token is denied (the middleware), and
- binding to a non-loopback host with NO device token configured is refused
  before the socket opens (:func:`assert_bind_safe`) — kinox never exposes an
  unauthenticated network surface.
"""

from __future__ import annotations

import time
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path

from daemon.remote_auth import authorize, load_tokens, requires_token
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from kernel.contracts import EventRecord
from kernel.metrics import MetricsSink


@dataclass
class RemoteConfig:
    """Wiring for the remote app (injectable so tests need no disk or network).

    *token_dir* is where per-device ``*.token`` files live; *tokens*, when given,
    is used verbatim instead of reading disk (test seam). *metrics_path* is the
    boundary log — auth denials are recorded there (honest observability).
    """

    token_dir: Path | None = None
    tokens: frozenset[str] | None = None
    metrics_path: Path = Path("/dev/null")


def assert_bind_safe(host: str | None, token_dir: Path | None) -> None:
    """Refuse to expose an unauthenticated network surface (fail-CLOSED startup).

    Raised before binding: a remote-reachable *host* with no device token would be
    open to anyone on the network. Loopback / Unix-socket binds are local-trust and
    always allowed.
    """
    if requires_token(host) and not load_tokens(token_dir):
        raise RuntimeError(
            f"refusing to bind kinox remote to {host!r} with no device token — "
            "create one under the token dir (see `kx remote pair`) or bind to "
            "loopback. kinox never exposes an unauthenticated network surface."
        )


@dataclass
class _State:
    """Mutable per-app state: the active token set + a denied-request counter."""

    tokens: frozenset[str]
    denied: int = 0


def create_remote_app(config: RemoteConfig | None = None) -> FastAPI:
    """Build the remote-control app: auth middleware + status (P3/P4 add routes)."""
    cfg = config or RemoteConfig()
    sink = MetricsSink(cfg.metrics_path)
    # Seeded at construction (so a test using the app without the lifespan still
    # has the injected tokens) and reloaded at startup (so a restart picks up
    # newly paired devices).
    st = _State(tokens=cfg.tokens if cfg.tokens is not None else frozenset())

    @asynccontextmanager
    async def lifespan(_app: FastAPI):  # pyright: ignore[reportUnusedFunction]
        if cfg.tokens is None:
            st.tokens = load_tokens(cfg.token_dir)
        yield

    app = FastAPI(title="kinox remote", version="0.1.0", lifespan=lifespan)

    @app.middleware("http")
    async def _auth(  # pyright: ignore[reportUnusedFunction]
        request: Request, call_next: object
    ) -> object:
        client_host = request.client.host if request.client else ""
        is_local = not requires_token(client_host)
        reason = authorize(request.headers, st.tokens, is_local=is_local)
        if reason is not None:
            st.denied += 1
            # Every refused request is a boundary record (vision §4.6) — the
            # reason never echoes the presented token (see remote_auth.authorize).
            sink.record(
                EventRecord(
                    task_id=f"remote-deny-{int(time.time() * 1000)}",
                    kind="remote_auth_denied",
                    tier="deterministic",
                )
            )
            return JSONResponse(
                {"error": {"type": "unauthorized", "message": reason}},
                status_code=401,
            )
        return await call_next(request)  # type: ignore[operator]

    @app.get("/remote/status")
    async def remote_status() -> dict[str, object]:  # pyright: ignore[reportUnusedFunction]
        return {
            "remote": "enabled",
            "paired_devices": len(st.tokens),
            "auth_denied": st.denied,
        }

    return app
