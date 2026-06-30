"""The parallel fan-out coordinator — the constitution's parallelism axiom.

Proves the guarantees that make "two agents at once" safe: the partition is
refused fail-CLOSED when slices overlap (before any agent runs), each agent's
writes are confined to its own slice, a cross-slice write is blocked (not a lost
edit — no override), reads are never restricted, and the agents actually run
concurrently rather than one-after-another.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable
from pathlib import Path
from typing import TypeVar

import pytest
from daemon.exec import BackendResponse, Call, Messages
from kernel.contracts import Tier
from kernel.metrics import MetricsSink
from products.agent.coordinator import (
    OverlapError,
    Slice,
    agent_runner,
    assert_disjoint,
    combine_guards,
    ownership_guard,
    run_parallel,
)
from products.agent.loop import AgentResult, Guard, GuardBlocked, run_agent
from products.agent.tools import default_registry

TIER = Tier.model("gemma-agentic:32k", where="local", backend="ollama")

_T = TypeVar("_T")


def _run(coro: Awaitable[_T]) -> _T:
    return asyncio.run(coro)  # type: ignore[arg-type]


def _sink() -> MetricsSink:
    return MetricsSink(Path("/dev/null"))


def _tool_call(call_id: str, name: str, arguments: str) -> dict[str, object]:
    return {
        "id": call_id,
        "type": "function",
        "function": {"name": name, "arguments": arguments},
    }


def _scripted_factory(turns: list[BackendResponse]) -> object:
    """A call_factory returning successive scripted backend responses."""
    box = {"i": 0}

    def factory(_schema: list[dict[str, object]]) -> Call:
        async def call(_tier: Tier, _messages: Messages) -> BackendResponse:
            i = box["i"]
            box["i"] = i + 1
            return turns[min(i, len(turns) - 1)]

        return call

    return factory


# --- assert_disjoint ---------------------------------------------------------


def test_disjoint_passes_on_separate_paths() -> None:
    root = Path("/repo")
    assert_disjoint(
        [Slice("a", ("a.txt",), "A"), Slice("b", ("b.txt",), "B")], root
    )  # no raise


def test_disjoint_allows_nested_owns_within_one_slice() -> None:
    # One slice owning both a dir and a file under it is fine — same agent.
    assert_disjoint([Slice("a", ("pkg/", "pkg/x.py"), "A")], Path("/repo"))


def test_disjoint_refuses_identical_claim() -> None:
    with pytest.raises(OverlapError):
        assert_disjoint(
            [Slice("a", ("x.py",), "A"), Slice("b", ("x.py",), "B")], Path("/repo")
        )


def test_disjoint_refuses_ancestor_overlap() -> None:
    # "pkg/" (B) contains "pkg/x.py" (A) → cross-slice overlap, refused.
    with pytest.raises(OverlapError):
        assert_disjoint(
            [Slice("a", ("pkg/x.py",), "A"), Slice("b", ("pkg/",), "B")],
            Path("/repo"),
        )


# --- ownership_guard ---------------------------------------------------------


def test_guard_blocks_write_outside_owned() -> None:
    g = ownership_guard(Path("/repo"), owned=("a.txt",), foreign=("b.txt",))
    with pytest.raises(GuardBlocked):
        g("write_file", '{"path": "b.txt", "content": "x"}')


def test_guard_allows_write_inside_owned() -> None:
    g = ownership_guard(Path("/repo"), owned=("pkg/",), foreign=("other/",))
    g("write_file", '{"path": "pkg/deep/x.py", "content": "x"}')


def test_guard_never_restricts_reads() -> None:
    g = ownership_guard(Path("/repo"), owned=("a.txt",), foreign=("b.txt",))
    # Reading another slice's file is allowed — observing cannot override.
    g("read_file", '{"path": "b.txt"}')
    g("list_dir", '{"path": "."}')


def test_guard_blocks_bash_reaching_into_foreign() -> None:
    g = ownership_guard(Path("/repo"), owned=("a/",), foreign=("b/",))
    with pytest.raises(GuardBlocked):
        g("run_bash", '{"command": "rm b/secret.txt"}')


def test_guard_allows_bash_within_neutral_ground() -> None:
    g = ownership_guard(Path("/repo"), owned=("a/",), foreign=("b/",))
    # Touches neither slice's owned set → allowed by the ownership guard.
    g("run_bash", '{"command": "echo hi"}')


def test_guard_fails_closed_on_unparseable_bash() -> None:
    g = ownership_guard(Path("/repo"), owned=("a/",), foreign=("b/",))
    with pytest.raises(GuardBlocked):
        g("run_bash", '{"command": "echo \\"unbalanced"}')


# --- combine_guards ----------------------------------------------------------


def test_combine_returns_first_denial() -> None:
    def deny(_n: str, _a: str) -> None:
        raise GuardBlocked("nope")
    def allow(_n: str, _a: str) -> None:
        pass
    with pytest.raises(GuardBlocked, match="nope"):
        combine_guards(allow, deny)("write_file", "{}")
    combine_guards(allow, allow)("write_file", "{}")
    combine_guards(None, allow)("write_file", "{}")


# --- run_parallel (integration) ----------------------------------------------


def test_run_parallel_refuses_overlap_before_spawning() -> None:
    spawned: list[str] = []

    async def run(s: Slice, _g: Guard) -> AgentResult:
        spawned.append(s.label)
        return AgentResult(final_text="ran")

    with pytest.raises(OverlapError):
        _run(
            run_parallel(
                [Slice("a", ("x",), "A"), Slice("b", ("x",), "B")],
                root=Path("/repo"),
                run=run,
            )
        )
    assert spawned == []  # fail-CLOSED: no agent was started


def test_run_parallel_partitions_writes_no_override(tmp_path: Path) -> None:
    # A is told to (1) try to clobber B's file — must be blocked — then (2) write
    # its own; B writes its own. The cross-slice write must NOT take effect.
    registry = default_registry(tmp_path, allow_write=True)
    factories = {
        "A": _scripted_factory(
            [
                BackendResponse(
                    content="",
                    tool_calls=[
                        _tool_call(
                            "a1",
                            "write_file",
                            '{"path": "b.txt", "content": "A-OVERRIDE"}',
                        )
                    ],
                    finish_reason="tool_calls",
                ),
                BackendResponse(
                    content="",
                    tool_calls=[
                        _tool_call(
                            "a2",
                            "write_file",
                            '{"path": "a.txt", "content": "A-OWN"}',
                        )
                    ],
                    finish_reason="tool_calls",
                ),
                BackendResponse(content="A done", finish_reason="stop"),
            ]
        ),
        "B": _scripted_factory(
            [
                BackendResponse(
                    content="",
                    tool_calls=[
                        _tool_call(
                            "b1",
                            "write_file",
                            '{"path": "b.txt", "content": "B-OWN"}',
                        )
                    ],
                    finish_reason="tool_calls",
                ),
                BackendResponse(content="B done", finish_reason="stop"),
            ]
        ),
    }

    async def run(s: Slice, guard: Guard) -> AgentResult:
        return await run_agent(
            s.task,
            tier=TIER,
            registry=registry,
            sink=_sink(),
            task_id=f"t:{s.label}",
            guard=guard,
            call_factory=factories[s.label],  # type: ignore[arg-type]
        )

    pairs = _run(
        run_parallel(
            [Slice("write a", ("a.txt",), "A"), Slice("write b", ("b.txt",), "B")],
            root=tmp_path,
            run=run,
        )
    )

    results = {s.label: r for s, r in pairs}
    # A's attempt to write into B's slice was blocked (visible in the trace)…
    assert any(step.kind == "blocked" for step in results["A"].steps)
    # …and B's file holds B's content — the override never happened.
    assert (tmp_path / "b.txt").read_text() == "B-OWN"
    assert (tmp_path / "a.txt").read_text() == "A-OWN"
    assert results["A"].stopped == "complete"
    assert results["B"].stopped == "complete"


def test_run_parallel_runs_agents_concurrently() -> None:
    # Each agent blocks until the other has started; sequential execution would
    # deadlock. Completing under a timeout proves they overlap.
    started = asyncio.Event()
    second = asyncio.Event()
    order: list[str] = []

    async def run(s: Slice, _g: Guard) -> AgentResult:
        if not started.is_set():
            started.set()
            await second.wait()  # first agent waits for the second to arrive
        else:
            second.set()
        order.append(s.label)
        return AgentResult(final_text=f"{s.label} done")

    async def drive() -> list[tuple[Slice, AgentResult]]:
        return await asyncio.wait_for(
            run_parallel(
                [Slice("one", ("a",), "A"), Slice("two", ("b",), "B")],
                root=Path("/repo"),
                run=run,
            ),
            timeout=2.0,
        )

    pairs = _run(drive())
    assert {s.label for s, _ in pairs} == {"A", "B"}
    assert set(order) == {"A", "B"}  # both ran; no deadlock → genuinely concurrent


def test_agent_runner_binds_run_agent(tmp_path: Path) -> None:
    # The production binding: agent_runner → run_agent, per-slice task id, shared
    # registry, coordinator-supplied guard.
    registry = default_registry(tmp_path, allow_write=True)
    factory = _scripted_factory([BackendResponse(content="ok", finish_reason="stop")])
    runner = agent_runner(
        tier=TIER,
        registry=registry,
        sink=_sink(),
        task_id="job",
        call_factory=factory,  # type: ignore[arg-type]
    )
    pairs = _run(
        run_parallel(
            [Slice("t", ("a.txt",), "A")], root=tmp_path, run=runner
        )
    )
    assert pairs[0][1].final_text == "ok"
