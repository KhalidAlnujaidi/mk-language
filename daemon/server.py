"""The FastAPI broker app + Unix-socket entrypoint (broker brick 1, spec §4.4).

Exposes an OpenAI-compatible surface over a Unix domain socket:

  - ``POST /v1/chat/completions`` — OpenAI-shape chat in, OpenAI-shape completion
    out. Acquires the single inference slot, probes a fresh manifest, builds the
    fallback chain, executes it through the injected backend, records one
    ``EventRecord``, and returns. An exhausted chain becomes a soft 503 with an
    OpenAI ``error`` object (the broker fails SOFT — spec §6).
  - ``GET /broker/route?model=…`` — the computed fallback chain, without
    executing (debug aid).
  - ``GET /broker/status`` — manifest summary, last tier used, recent events.

The backend transport and manifest source are injected via ``BrokerConfig`` so
the app is fully testable offline (``TestClient`` + a stub backend). The real
transport is :func:`daemon.backends.make_dispatch`, which routes each tier to its
backend's OpenAI-compatible ``/v1/chat/completions`` endpoint (Ollama, vLLM, or
llama.cpp).

Launch (production):
    uvicorn daemon.server:app --uds /run/kinox/broker.sock
The socket path is configurable via ``KINOX_BROKER_SOCKET``; its parent dir is
created if absent.
"""

from __future__ import annotations

import dataclasses
import json
import os
import time
from collections.abc import Callable
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from kernel.contracts import EventRecord
from kernel.jsonutil import as_dict
from kernel.manifest import Manifest
from kernel.manifest import probe as default_probe
from kernel.metrics import MetricsSink

from daemon.backends import make_dispatch
from daemon.exec import (
    Call,
    ChainExhausted,
    execute,
    tier_label,
)
from daemon.fallback import build_chain
from daemon.hooks import HookChain
from daemon.outbox import Outbox, OutboxEntry
from daemon.resources import ResourceSnapshot
from daemon.resources import sample as default_resources
from daemon.serializer import Serializer
from daemon.tracing import incoming_trace, init_tracing

# How many recent events ``/broker/status`` surfaces.
_RECENT_EVENTS_LIMIT = 20

# Default Unix socket path for the broker.
DEFAULT_SOCKET_PATH = os.environ.get("KINOX_BROKER_SOCKET", "/run/kinox/broker.sock")

# Default JSONL sink for EventRecords.
_DEFAULT_METRICS_PATH = Path(
    os.environ.get(
        "KINOX_BROKER_METRICS", str(Path.home() / ".kinox" / "broker-events.jsonl")
    )
)

# Default durable outbox for the production broker (hard truth #4). The injectable
# BrokerConfig.outbox_path defaults to None so create_app stays side-effect-free
# for tests; the module-level production ``app`` wires this real path explicitly.
_DEFAULT_OUTBOX_PATH = Path(
    os.environ.get(
        "KINOX_BROKER_OUTBOX", str(Path.home() / ".kinox" / "broker-outbox.jsonl")
    )
)


@dataclasses.dataclass(frozen=True)
class BrokerConfig:
    """Injectable wiring for the broker app.

    ``probe`` returns a fresh ``Manifest`` per request; ``call`` is the backend
    transport (real httpx → Ollama in production, a stub in tests); events are
    appended to ``metrics_path``.
    """

    probe: Callable[[], Manifest] = default_probe
    call: Call | None = None
    metrics_path: Path = _DEFAULT_METRICS_PATH
    resources: Callable[[], ResourceSnapshot] = default_resources
    outbox_path: Path | None = None
    #: Optional pre-inference hook chain (Brick B — thesis #2).
    hook_chain: HookChain | None = None


# --- OpenAI-shape helpers -----------------------------------------------------


def _completion_body(content: str, model: str, event: EventRecord) -> dict[str, object]:
    """Render an OpenAI ``chat.completion`` body from a result + event."""
    return {
        "id": f"chatcmpl-{event.task_id}",
        "object": "chat.completion",
        "created": int(time.time()),
        "model": model,
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": content},
                "finish_reason": "stop",
            }
        ],
        "usage": {
            "prompt_tokens": event.tokens_in,
            "completion_tokens": event.tokens_out,
            "total_tokens": (
                (event.tokens_in or 0) + (event.tokens_out or 0)
                if event.tokens_in is not None or event.tokens_out is not None
                else None
            ),
        },
    }


def _coerce_messages(raw: object) -> list[dict[str, object]]:
    """Normalise an incoming ``messages`` field to a list of chat dicts.

    Returns ``Messages`` (``dict`` values typed ``object``) so the result feeds
    ``execute`` directly — ``dict`` is invariant, so ``dict[str, str]`` would
    not satisfy the ``list[dict[str, object]]`` parameter.
    """
    if not isinstance(raw, list):
        return []
    items: list[object] = list(raw)  # type: ignore[arg-type]  # JSON list is untyped
    out: list[dict[str, object]] = []
    for item in items:
        coerced = as_dict(item)
        if coerced:
            out.append({k: str(v) for k, v in coerced.items()})
    return out


def _error_response(message: str, *, type_: str, status: int) -> JSONResponse:
    """An OpenAI-shape error object (the broker fails SOFT — spec §6)."""
    return JSONResponse(
        status_code=status,
        content={"error": {"message": message, "type": type_, "code": None}},
    )


# --- Crash recovery (hard truth #4) -------------------------------------------


def recover_pending(outbox: Outbox) -> list[OutboxEntry]:
    """Reconcile effects left ``pending`` by a prior crash; return what was resolved.

    On startup, any outbox entry still ``pending`` was logged BEFORE execution but
    never reached a terminal record — the broker died mid-flight. The broker's only
    effect kind is ``inference``, which is NOT safe to replay post-crash: the
    requesting client is long gone and a cloud call would cost money for no
    recipient. So recovery RECONCILES each orphan to ``failed`` (its honest terminal
    state) rather than re-running it — clearing the phantom pending set and leaving
    a truthful, append-only audit trail (the ``failed`` record is appended; the
    original ``pending`` line survives). When the broker grows genuinely replayable
    (idempotent) effect kinds, branch on ``entry.kind`` here to re-apply them.
    """
    orphans = outbox.pending()
    for entry in orphans:
        outbox.mark_failed(entry.id)
    return orphans


# --- App factory --------------------------------------------------------------


def create_app(config: BrokerConfig | None = None) -> FastAPI:
    """Build the broker FastAPI app wired from *config* (injectable for tests)."""
    cfg = config or BrokerConfig()
    call: Call = cfg.call or make_dispatch()
    serializer = Serializer()
    hook_chain = cfg.hook_chain
    outbox: Outbox | None = Outbox(cfg.outbox_path) if cfg.outbox_path else None
    sink = MetricsSink(cfg.metrics_path)
    # In-memory state for /broker/status: the last tier used (null until first call)
    # and the ids reconciled from a prior crash on this startup (hard truth #4).
    state: dict[str, object] = {"last_tier_used": None, "recovered_on_start": []}

    @asynccontextmanager
    async def lifespan(_app: FastAPI):  # pyright: ignore[reportUnusedFunction]
        # Activate the daemon's own OTel tracer (vision §7) so the broker process
        # emits spans and can join an external caller's trace. No-op unless
        # KINOX_OTEL=1 and the otel extra is installed; fail-soft otherwise.
        init_tracing()
        # Crash recovery runs when the daemon STARTS (uvicorn lifespan / a
        # `with TestClient(...)` block) — never on mere import — so importing this
        # module to build the app touches no outbox file.
        if outbox is not None:
            state["recovered_on_start"] = [e.id for e in recover_pending(outbox)]
        yield

    app = FastAPI(title="kinox broker", version="0.1.0", lifespan=lifespan)

    @app.post("/v1/chat/completions")
    async def chat_completions(  # pyright: ignore[reportUnusedFunction]
        request: dict[str, object],
        http_request: Request,
    ) -> object:
        # Join the caller's trace if the request carries a W3C traceparent, so the
        # broker's spans (broker.execute → …) nest under the remote span — one trace
        # across the process boundary. A no-op when tracing is off.
        with incoming_trace(http_request.headers):
            messages = _coerce_messages(request.get("messages"))
            requested = request.get("model")
            preferred = requested if isinstance(requested, str) else None
            task_id = f"chat-{int(time.time() * 1000)}"

            # Run the pre-inference hook chain before any model call.
            # CLOSED hooks block; SOFT hooks inject context (thesis #2).
            if hook_chain is not None:
                hook_input: dict[str, object] = {
                    "messages": messages,
                    "model": preferred or "auto",
                }
                hook_result = await hook_chain.run(hook_input)
                if hook_result.decision == "deny":
                    return _error_response(
                        hook_result.reason or "blocked by hook",
                        type_="hook_denied",
                        status=403,
                    )

            # Hard truth #4: record the intended effect BEFORE execution —
            # triples as crash-replay source, audit trail, and correction signal.
            if outbox is not None:
                outbox.append(
                    id=task_id,
                    kind="inference",
                    payload=json.dumps(
                        {
                            "model": preferred or "auto",
                            "message_count": len(messages),
                            "timestamp": int(time.time()),
                        }
                    ),
                )

            async with serializer.slot():
                manifest = cfg.probe()
                chain = build_chain(manifest, preferred)
                try:
                    result = await execute(
                        chain,
                        messages,
                        call=call,
                        task_id=task_id,
                    )
                except ChainExhausted as exc:
                    if outbox is not None:
                        outbox.mark_failed(task_id)
                    sink.record(exc.event)
                    state["last_tier_used"] = exc.event.tier
                    return _error_response(
                        "no model tier could serve this request",
                        type_="broker_chain_exhausted",
                        status=503,
                    )

                if outbox is not None:
                    outbox.mark_done(task_id)
                sink.record(result.event)
                state["last_tier_used"] = result.event.tier
                model_name = result.tier_used.model_name or "unknown"
                return _completion_body(result.content, model_name, result.event)

    @app.get("/broker/route")
    async def broker_route(  # pyright: ignore[reportUnusedFunction]
        model: str | None = None,
    ) -> dict[str, object]:
        manifest = cfg.probe()
        chain = build_chain(manifest, model)
        return {
            "preferred": model,
            "chain": [
                {
                    "model_name": t.model_name,
                    "where": t.where,
                    "label": tier_label(t),
                }
                for t in chain
            ],
        }

    @app.get("/broker/status")
    async def broker_status() -> dict[str, object]:  # pyright: ignore[reportUnusedFunction]
        manifest = cfg.probe()
        recent = sink.read_all()[-_RECENT_EVENTS_LIMIT:]
        snap = cfg.resources()
        return {
            "manifest": {
                "cpu_count": manifest.cpu_count,
                "ram_gb": manifest.ram_gb,
                "gpu_vram_gb": manifest.gpu_vram_gb,
                "local_models": [
                    {"name": m.name, "backend": m.backend}
                    for m in manifest.local_models
                ],
                "cloud_available": manifest.cloud_available,
            },
            "resources": {
                "vram_total_gb": snap.vram_total_gb,
                "vram_used_gb": snap.vram_used_gb,
                "vram_free_gb": snap.vram_free_gb,  # derived property
                "cpu_percent": snap.cpu_percent,
                "ram_used_gb": snap.ram_used_gb,
                "ram_total_gb": snap.ram_total_gb,
            },
            "last_tier_used": state["last_tier_used"],
            "recovered_on_start": state["recovered_on_start"],
            "recent_events": [dataclasses.asdict(e) for e in recent],
        }

    return app


def _ensure_socket_dir(socket_path: str) -> None:
    """Create the Unix socket's parent directory if absent (spec §4.4)."""
    Path(socket_path).parent.mkdir(parents=True, exist_ok=True)


# The default app for ``uvicorn daemon.server:app --uds …``. The production broker
# wires the durable outbox (hard truth #4) so every inference is logged before
# execution and a crash is reconciled on the next startup via the lifespan hook.
app = create_app(BrokerConfig(outbox_path=_DEFAULT_OUTBOX_PATH))


def serve(socket_path: str = DEFAULT_SOCKET_PATH) -> None:  # pragma: no cover
    """Bind the broker to a Unix domain socket and serve (spec §4.4).

    Creates the socket's parent directory if absent, then hands off to uvicorn.
    Excluded from coverage: this is the live entrypoint, exercised end-to-end
    rather than in the offline unit suite.
    """
    import uvicorn

    _ensure_socket_dir(socket_path)
    uvicorn.run(app, uds=socket_path)


if __name__ == "__main__":  # pragma: no cover
    serve()