"""End-to-end OpenTelemetry tracing across groom / agent / broker (vision §7).

Skips when the optional ``otel`` extra is absent. Installs an in-memory OTel
exporter through the real ``products.telemetry`` adapter + the kernel seam, runs
the actual components, and asserts ONE connected span tree — the proof that
``span(...)`` calls scattered across the layers stitch into a single trace.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

pytest.importorskip("opentelemetry")

from daemon.exec import BackendResponse, Call, Messages, execute  # noqa: E402
from kernel.contracts import Tier  # noqa: E402
from kernel.manifest import Manifest  # noqa: E402
from kernel.metrics import MetricsSink  # noqa: E402
from kernel.tracing import set_tracer  # noqa: E402
from opentelemetry.sdk.trace import TracerProvider  # noqa: E402
from opentelemetry.sdk.trace.export import SimpleSpanProcessor  # noqa: E402
from opentelemetry.sdk.trace.export.in_memory_span_exporter import (  # noqa: E402
    InMemorySpanExporter,
)
from products.agent.loop import run_agent  # noqa: E402
from products.agent.tools import Tool, ToolRegistry  # noqa: E402
from products.groom.pipeline import groom  # noqa: E402
from products.telemetry import init_tracing  # noqa: E402
from products.telemetry.otel import _OtelTracer  # noqa: E402

_TIER = Tier.model("gemma-agentic:32k", where="local", backend="ollama")


@pytest.fixture
def exporter() -> InMemorySpanExporter:
    """Install an in-memory OTel tracer via the real adapter; reset after."""
    exp = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exp))
    set_tracer(_OtelTracer(provider.get_tracer("test")))
    yield exp
    set_tracer(None)


def _by_id(exp: InMemorySpanExporter) -> dict[int, tuple[str, int | None]]:
    """Map span_id → (name, parent_span_id)."""
    tree: dict[int, tuple[str, int | None]] = {}
    for s in exp.get_finished_spans():
        sid = s.context.span_id
        pid = s.parent.span_id if s.parent is not None else None
        tree[sid] = (s.name, pid)
    return tree


def _ancestors(tree: dict[int, tuple[str, int | None]], sid: int) -> set[str]:
    names: set[str] = set()
    _, pid = tree[sid]
    while pid is not None and pid in tree:
        names.add(tree[pid][0])
        _, pid = tree[pid]
    return names


def _names(tree: dict[int, tuple[str, int | None]]) -> list[str]:
    return [n for n, _ in tree.values()]


# --- init_tracing fail-soft ----------------------------------------------------


def test_init_tracing_disabled_returns_false() -> None:
    set_tracer(None)
    assert init_tracing(enabled=False) is False


# --- the agent trace tree ------------------------------------------------------


def _scripted_factory(turns: list[BackendResponse]):
    box = {"i": 0}

    def factory(_schema: list[dict[str, object]]) -> Call:
        async def call(_t: Tier, _m: Messages) -> BackendResponse:
            i = box["i"]
            box["i"] = i + 1
            return turns[min(i, len(turns) - 1)]

        return call

    return factory


def _echo_registry() -> ToolRegistry:
    reg = ToolRegistry()
    reg.register(
        Tool(
            name="echo",
            description="echo",
            parameters={"type": "object", "properties": {"x": {"type": "string"}}},
            handler=lambda a: f"echo:{a.get('x')}",
        )
    )
    return reg


def test_agent_run_emits_one_connected_trace(
    exporter: InMemorySpanExporter,
) -> None:
    tool_turn = BackendResponse(
        content="",
        tool_calls=[
            {
                "id": "c1",
                "type": "function",
                "function": {"name": "echo", "arguments": '{"x": "hi"}'},
            }
        ],
        finish_reason="tool_calls",
    )
    final_turn = BackendResponse(content="done")

    asyncio.run(
        run_agent(
            "do it",
            tier=_TIER,
            registry=_echo_registry(),
            sink=MetricsSink(Path("/dev/null")),
            task_id="trace-1",
            call_factory=_scripted_factory([tool_turn, final_turn]),
            max_turns=4,
        )
    )

    tree = _by_id(exporter)
    names = _names(tree)
    # Every component boundary shows up as a span.
    assert "agent.run" in names
    assert "broker.execute" in names
    assert "broker.tier" in names
    assert "agent.tool:echo" in names

    # And they form ONE tree rooted at agent.run: the tool span and the broker
    # spans all descend from the single agent.run span.
    tool_sid = next(sid for sid, (n, _) in tree.items() if n == "agent.tool:echo")
    assert "agent.run" in _ancestors(tree, tool_sid)
    exec_sid = next(sid for sid, (n, _) in tree.items() if n == "broker.execute")
    assert "agent.run" in _ancestors(tree, exec_sid)
    tier_sid = next(sid for sid, (n, _) in tree.items() if n == "broker.tier")
    assert {"broker.execute", "agent.run"} <= _ancestors(tree, tier_sid)


def test_broker_execute_nests_tier_spans(exporter: InMemorySpanExporter) -> None:
    async def call(_t: Tier, _m: Messages) -> BackendResponse:
        return BackendResponse(content="ok", tokens_in=1, tokens_out=1)

    asyncio.run(execute([_TIER], [{"role": "user", "content": "hi"}], call=call,
                        task_id="trace-2"))
    tree = _by_id(exporter)
    tier_sid = next(sid for sid, (n, _) in tree.items() if n == "broker.tier")
    assert "broker.execute" in _ancestors(tree, tier_sid)


def test_groom_emits_a_span(exporter: InMemorySpanExporter, tmp_path: Path) -> None:
    manifest = Manifest(
        cpu_count=4,
        ram_gb=8.0,
        gpu_vram_gb=None,
        local_models=(),
        cloud_available=False,
    )
    groom(
        "hello world",
        manifest=manifest,
        sink=MetricsSink(Path("/dev/null")),
        cwd=tmp_path,
        task_id="trace-3",
    )
    assert "groom" in _names(_by_id(exporter))
