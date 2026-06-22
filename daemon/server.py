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
transport is :func:`ollama_call`, an httpx client against Ollama's OpenAI-
compatible ``/v1/chat/completions`` endpoint.

Launch (production):
    uvicorn daemon.server:app --uds /run/kinox/broker.sock
The socket path is configurable via ``KINOX_BROKER_SOCKET``; its parent dir is
created if absent.
"""

from __future__ import annotations

import dataclasses
import os
import time
from collections.abc import Callable
from pathlib import Path

import httpx
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from kernel.contracts import EventRecord, Tier
from kernel.manifest import Manifest
from kernel.manifest import probe as default_probe
from kernel.metrics import MetricsSink

from daemon.exec import (
    BackendError,
    BackendResponse,
    Call,
    ChainExhausted,
    execute,
    tier_label,
)
from daemon.fallback import build_chain
from daemon.serializer import Serializer

# How many recent events ``/broker/status`` surfaces.
_RECENT_EVENTS_LIMIT = 20

# Default Ollama endpoint (OpenAI-compatible). Overridable via env.
_OLLAMA_BASE_URL = os.environ.get("KINOX_OLLAMA_URL", "http://127.0.0.1:11434/v1")

# Default Unix socket path for the broker.
DEFAULT_SOCKET_PATH = os.environ.get("KINOX_BROKER_SOCKET", "/run/kinox/broker.sock")

# Default JSONL sink for EventRecords.
_DEFAULT_METRICS_PATH = Path(
    os.environ.get(
        "KINOX_BROKER_METRICS", str(Path.home() / ".kinox" / "broker-events.jsonl")
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


# --- Untyped-JSON coercion helpers -------------------------------------------


def _as_dict(value: object) -> dict[str, object]:
    """Return *value* as a ``dict[str, object]`` if it is a mapping, else ``{}``."""
    if isinstance(value, dict):
        return {str(k): v for k, v in value.items()}  # type: ignore[misc]
    return {}


def _as_int(value: object) -> int | None:
    """Return *value* as an ``int`` if it is one (and not a bool), else ``None``."""
    return value if isinstance(value, int) and not isinstance(value, bool) else None


# --- Real backend transport (httpx → Ollama) ---------------------------------


async def ollama_call(tier: Tier, messages: list[dict[str, str]]) -> BackendResponse:
    """Execute one chat completion against Ollama's OpenAI-compatible endpoint.

    Maps transport/timeout/5xx failures to a retryable ``BackendError`` so the
    executor falls through to the next tier. Tokens are read exact from Ollama's
    ``usage`` block (``tokens_exact=True``); a cloud tier would instead estimate.
    """
    payload = {"model": tier.model_name, "messages": messages, "stream": False}
    try:
        async with httpx.AsyncClient(
            base_url=_OLLAMA_BASE_URL, timeout=120.0
        ) as client:
            resp = await client.post("/chat/completions", json=payload)
            if resp.status_code >= 500:
                raise BackendError(f"ollama {resp.status_code}", retryable=True)
            resp.raise_for_status()
            data: dict[str, object] = resp.json()
    except BackendError:
        raise
    except httpx.HTTPError as exc:
        raise BackendError(f"ollama transport: {exc}", retryable=True) from exc

    raw_choices = data.get("choices")
    if not isinstance(raw_choices, list) or not raw_choices:
        raise BackendError("ollama returned no choices", retryable=True)
    choices: list[object] = list(raw_choices)  # type: ignore[arg-type]  # untyped JSON
    first = _as_dict(choices[0])
    message = _as_dict(first.get("message"))
    content = message.get("content", "")
    usage = _as_dict(data.get("usage"))
    return BackendResponse(
        content=str(content),
        tokens_in=_as_int(usage.get("prompt_tokens")),
        tokens_out=_as_int(usage.get("completion_tokens")),
        tokens_exact=tier.where == "local",
    )


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


def _coerce_messages(raw: object) -> list[dict[str, str]]:
    """Normalise an incoming ``messages`` field to a list of chat dicts."""
    if not isinstance(raw, list):
        return []
    items: list[object] = list(raw)  # type: ignore[arg-type]  # JSON list is untyped
    out: list[dict[str, str]] = []
    for item in items:
        as_dict = _as_dict(item)
        if as_dict:
            out.append({k: str(v) for k, v in as_dict.items()})
    return out


def _error_response(message: str, *, type_: str, status: int) -> JSONResponse:
    """An OpenAI-shape error object (the broker fails SOFT — spec §6)."""
    return JSONResponse(
        status_code=status,
        content={"error": {"message": message, "type": type_, "code": None}},
    )


# --- App factory --------------------------------------------------------------


def create_app(config: BrokerConfig | None = None) -> FastAPI:
    """Build the broker FastAPI app wired from *config* (injectable for tests)."""
    cfg = config or BrokerConfig()
    call: Call = cfg.call or ollama_call
    serializer = Serializer()
    sink = MetricsSink(cfg.metrics_path)
    # In-memory record of the last tier used (status debug aid; null until first call).
    state: dict[str, str | None] = {"last_tier_used": None}

    app = FastAPI(title="kinox broker", version="0.1.0")

    @app.post("/v1/chat/completions")
    async def chat_completions(  # pyright: ignore[reportUnusedFunction]
        request: dict[str, object],
    ) -> object:
        messages = _coerce_messages(request.get("messages"))
        requested = request.get("model")
        preferred = requested if isinstance(requested, str) else None
        task_id = f"chat-{int(time.time() * 1000)}"

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
                sink.record(exc.event)
                state["last_tier_used"] = exc.event.tier
                return _error_response(
                    "no model tier could serve this request",
                    type_="broker_chain_exhausted",
                    status=503,
                )

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
        return {
            "manifest": {
                "cpu_count": manifest.cpu_count,
                "ram_gb": manifest.ram_gb,
                "gpu_vram_gb": manifest.gpu_vram_gb,
                "local_models": [m.name for m in manifest.local_models],
                "cloud_available": manifest.cloud_available,
            },
            "last_tier_used": state["last_tier_used"],
            "recent_events": [dataclasses.asdict(e) for e in recent],
        }

    return app


def _ensure_socket_dir(socket_path: str) -> None:
    """Create the Unix socket's parent directory if absent (spec §4.4)."""
    Path(socket_path).parent.mkdir(parents=True, exist_ok=True)


# The default app for ``uvicorn daemon.server:app --uds …``.
app = create_app()


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
