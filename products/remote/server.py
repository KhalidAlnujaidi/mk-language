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
from collections.abc import Awaitable, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from pathlib import Path

from daemon.remote_auth import authorize, load_tokens, requires_token
from daemon.tracing import incoming_trace
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from kernel.contracts import EventRecord
from kernel.metrics import MetricsSink

from products.agent.loop import AgentResult

#: A runner drives one remote agent turn: ``(task, history, spent_offset) ->
#: AgentResult``. Injected so tests need no model/network; production binds the
#: real jailed ``run_agent`` (see :func:`_make_default_runner`).
RunFn = Callable[[str, list[dict[str, object]], int], Awaitable[AgentResult]]

#: Conversation pairs kept per remote session (mirrors the TUI's history cap).
_MAX_HISTORY_PAIRS = 10


@dataclass
class RemoteConfig:
    """Wiring for the remote app (injectable so tests need no disk or network).

    *token_dir* is where per-device ``*.token`` files live; *tokens*, when given,
    is used verbatim instead of reading disk (test seam). *metrics_path* is the
    boundary log — auth denials are recorded there (honest observability). *root*
    is the jail every remote agent session is confined to; *session_token_budget*
    caps the cumulative tokens of one session (carried across turns); *run* is the
    injectable turn runner (default: the real jailed ``run_agent``).
    """

    token_dir: Path | None = None
    tokens: frozenset[str] | None = None
    metrics_path: Path = Path("/dev/null")
    root: Path = field(default_factory=Path.cwd)
    session_token_budget: int | None = None
    run: RunFn | None = None


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


@dataclass
class _RemoteSession:
    """Per-session continuity: conversation history + cumulative token spend.

    HTTP is stateless, so a remote ``session_id`` is the thread of memory: history
    is carried into the next turn and the spend accrues across turns (reusing the
    agent loop's ``spent_offset``), so a per-session budget governs the whole
    conversation rather than one call.
    """

    history: list[dict[str, object]] = field(
        default_factory=list[dict[str, object]]
    )
    tokens_spent: int = 0


def _make_default_runner(cfg: RemoteConfig, sink: MetricsSink) -> RunFn:
    """The production runner: a jailed ``run_agent`` confined to ``cfg.root``.

    Built lazily (no probe at app-construction); the live model/tier resolution is
    exercised end-to-end, not in the offline unit suite — tests inject ``cfg.run``.
    """

    async def run(  # pragma: no cover - live model path
        task: str, history: list[dict[str, object]], spent_offset: int
    ) -> AgentResult:
        from daemon.brain import brain_tier
        from kernel.contracts import Tier
        from kernel.manifest import probe

        from products.agent import (
            default_registry,
            project_root_guard,
            run_agent,
        )
        from products.agent.budget import TokenBudget
        from products.agent.coordinator import combine_guards
        from products.agent.rails import protected_rails_guard
        from products.capabilities.registry import CapabilityRegistry

        manifest = probe()
        local = manifest.local_models
        local_tier = (
            Tier.model(local[0].name, where="local", backend=local[0].backend)
            if local
            else None
        )
        tier = brain_tier(fallback=local_tier)
        if tier is None:
            raise RuntimeError("no model available (set ZAI_API_KEY or a local model)")

        skills = CapabilityRegistry.from_claude_dir(cfg.root / ".claude")
        registry = default_registry(
            cfg.root, skills=skills, allow_bash=True, allow_write=True
        )
        guard = combine_guards(
            project_root_guard(cfg.root), protected_rails_guard(cfg.root)
        )
        budget = (
            TokenBudget(limit=cfg.session_token_budget)
            if cfg.session_token_budget
            else None
        )
        return await run_agent(
            task,
            tier=tier,
            registry=registry,
            sink=sink,
            task_id=f"remote-{int(time.time() * 1000)}",
            history=history,
            spent_offset=spent_offset,
            token_budget=budget,
            guard=guard,
            fallback=local_tier,
        )

    return run


def create_remote_app(config: RemoteConfig | None = None) -> FastAPI:
    """Build the remote-control app: auth middleware + status (P3/P4 add routes)."""
    cfg = config or RemoteConfig()
    sink = MetricsSink(cfg.metrics_path)
    runner: RunFn = cfg.run or _make_default_runner(cfg, sink)
    sessions: dict[str, _RemoteSession] = {}
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
            "active_sessions": len(sessions),
        }

    @app.post("/v1/agent/run")
    async def agent_run(  # pyright: ignore[reportUnusedFunction]
        request: dict[str, object], http_request: Request
    ) -> object:
        task = request.get("task")
        if not isinstance(task, str) or not task.strip():
            return JSONResponse(
                {"error": {"type": "bad_request", "message": "'task' is required"}},
                status_code=400,
            )
        raw_sid = request.get("session_id")
        sid = raw_sid if isinstance(raw_sid, str) and raw_sid else "default"
        session = sessions.setdefault(sid, _RemoteSession())

        # Join the caller's trace if present, so a remote device's span and the
        # agent's spans form ONE trace across the network boundary (vision §7).
        try:
            with incoming_trace(http_request.headers):
                result = await runner(task, session.history, session.tokens_spent)
        except Exception as exc:  # noqa: BLE001 — fail-soft: never 500 the caller
            return JSONResponse(
                {"error": {"type": "agent_unavailable", "message": str(exc)}},
                status_code=503,
            )

        # Persist the turn so the next call on this session remembers it; carry the
        # cumulative spend forward so the per-session budget continues to govern.
        if result.final_text:
            session.history.append({"role": "user", "content": task})
            session.history.append({"role": "assistant", "content": result.final_text})
            while len(session.history) > _MAX_HISTORY_PAIRS * 2:
                session.history.pop(0)
        session.tokens_spent = result.tokens_spent

        return {
            "session_id": sid,
            "final_text": result.final_text,
            "stopped": result.stopped,
            "turns": result.turns,
            "tokens_spent": result.tokens_spent,
            "steps": [
                {"kind": s.kind, "name": s.name, "detail": s.detail}
                for s in result.steps
                if s.kind in ("tool", "blocked")
            ],
        }

    return app
