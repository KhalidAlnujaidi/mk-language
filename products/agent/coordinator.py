"""Fan out one job to several agents in parallel — over disjoint slices.

The governed pipeline can run two (or more) agents at once. The instant work
runs in parallel the failure mode is no longer "too slow" — it is two agents
quietly editing the same file and one silently winning. This module is the
coordinator that makes that impossible: it partitions the work into slices, each
owning a disjoint set of paths, **proves the owned sets are disjoint before a
single agent is spawned** (fail-CLOSED, thesis #2), and gives each agent a guard
that refuses any write — direct or through the shell — that reaches into another
agent's slice.

The consequence is the constitution's parallelism axiom made executable: there is
no work to collapse and none to override. No agent's output can shadow another's,
and there is no master agent silently merging two parallel results — a conflict
surfaces as a refused action in the trace, never as a lost edit. Reads may overlap
freely (observing a file cannot override it); only writes are partitioned.

Pure logic, no TTY. The agent runner is injected (*run*) so the suite drives it
offline with a scripted backend — the same boundary-injection discipline as
``products/agent/loop.py``.
"""

from __future__ import annotations

import asyncio
import json
import shlex
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

from kernel.contracts import Tier
from kernel.jsonutil import as_dict
from kernel.metrics import MetricsSink

from products.agent.loop import AgentResult, Guard, run_agent

# ``_candidate_paths`` is a deliberate reuse (Rule Zero) of the sibling module's
# lexical path-token splitter — the same one ``run_bash``'s jail uses — so the
# ownership guard parses shell paths identically to the root guard.
from products.agent.tools import (
    ToolRegistry,
    _candidate_paths,  # noqa: PLC2701 # pyright: ignore[reportPrivateUsage]
    project_root_guard,
)


@dataclass(frozen=True)
class Slice:
    """One agent's assignment in a fan-out: a task and the paths it exclusively owns.

    *owned* are path prefixes (files or directories, relative to the shared root)
    the agent may write — its slice of the work. The coordinator guarantees owned
    sets are disjoint across slices, so no two agents ever write the same file. A
    slice with empty *owned* is a pure reader: it may observe the whole root but
    write nothing (fail-CLOSED). *label* names the slice in the trace and task id.
    """

    task: str
    owned: tuple[str, ...] = ()
    label: str = ""


class OverlapError(ValueError):
    """Two slices claim overlapping owned paths — refused before any agent runs.

    Raised by :func:`assert_disjoint` so a partition that would let two parallel
    agents fight over a file fails CLOSED at setup time, not as a lost edit later.
    """


#: Spawns one agent for a slice under the boundary *guard* the coordinator built.
#: Injected so production binds the real :func:`run_agent` while tests bind a fake.
RunSlice = Callable[[Slice, Guard], Awaitable[AgentResult]]


def _under(path: Path, bases: Sequence[Path]) -> bool:
    """True if *path* is one of *bases* or lives inside one of them."""
    return any(path == b or b in path.parents for b in bases)


def assert_disjoint(slices: Sequence[Slice], root: Path) -> None:
    """Refuse the partition unless every slice owns a disjoint set of paths.

    Two owned prefixes overlap when they resolve to the same path or one is an
    ancestor of the other (e.g. ``products/`` and ``products/agent/x.py``). Owned
    entries *within* a single slice may overlap freely — only cross-slice claims
    are a conflict. Fails CLOSED (raises :class:`OverlapError`) on the first
    overlap so no agent is ever spawned into a contested file.
    """
    root = Path(root)
    claims: list[tuple[Path, int, str]] = []
    for idx, s in enumerate(slices):
        label = s.label or f"slice[{idx}]"
        for o in s.owned:
            claims.append(((root / o).resolve(), idx, label))
    for i in range(len(claims)):
        pi, ii, li = claims[i]
        for j in range(i + 1, len(claims)):
            pj, ij, lj = claims[j]
            if ii == ij:  # same slice — nested owns are fine
                continue
            if pi == pj or pi in pj.parents or pj in pi.parents:
                raise OverlapError(
                    f"slices {li!r} and {lj!r} both claim overlapping paths "
                    f"({pi} vs {pj}) — parallel agents may not share a write target"
                )


def ownership_guard(
    root: Path, owned: Sequence[str], foreign: Sequence[str]
) -> Guard:
    """A pre-dispatch guard that confines an agent's *writes* to its own slice.

    A ``write_file`` is allowed only when its target resolves inside *owned*; a
    ``run_bash`` is refused when it lexically references any path inside *foreign*
    (another agent's slice). Reads are never restricted — observing a file cannot
    override it. Fails CLOSED (thesis #2): an unparseable shell command, or a
    write to an unowned path, is denied. This is the mechanism behind the
    constitution's parallelism axiom — one agent physically cannot touch another's
    work, so there is nothing to collapse or override.
    """
    root_p = Path(root)
    owned_r = [(root_p / o).resolve() for o in owned]
    foreign_r = [(root_p / o).resolve() for o in foreign]

    def guard(name: str, args_json: str) -> str | None:
        try:
            parsed: object = json.loads(args_json) if args_json else {}
        except json.JSONDecodeError:
            return None  # malformed args degrade to a fail-soft dispatch error
        args = as_dict(parsed)  # dict[str, object], {} for a non-object shape
        if name == "write_file":
            rel = str(args.get("path", ""))
            target = (root_p / rel).resolve()
            if not _under(target, owned_r):
                return (
                    f"write to {rel!r} is outside this agent's slice — that path "
                    "belongs to another agent (no override across slices)"
                )
            return None
        if name == "run_bash":
            command = str(args.get("command", ""))
            try:
                tokens = shlex.split(command, comments=False, posix=True)
            except ValueError:
                return "command could not be parsed for slice-ownership safety"
            for tok in tokens:
                for cand in _candidate_paths(tok):
                    if _under((root_p / cand).resolve(), foreign_r):
                        return (
                            f"path {cand!r} is owned by another agent's slice — "
                            "parallel agents may not reach into each other's work"
                        )
            return None
        return None

    return guard


def combine_guards(*guards: Guard | None) -> Guard:
    """Chain guards: return the first denial, or ``None`` if all pass.

    Order matters only for *which* denial message surfaces; any single denial
    blocks the call (fail-CLOSED). Used to layer the slice-ownership guard on top
    of the project-root jail so both boundaries hold at once.
    """
    active = [g for g in guards if g is not None]

    def guard(name: str, args_json: str) -> str | None:
        for g in active:
            denial = g(name, args_json)
            if denial is not None:
                return denial
        return None

    return guard


async def run_parallel(
    slices: Sequence[Slice], *, root: Path, run: RunSlice
) -> list[tuple[Slice, AgentResult]]:
    """Run every slice concurrently, each jailed to its own write boundary.

    Validates the partition is disjoint (fail-CLOSED *before* any agent spawns),
    then for each slice composes the project-root jail with its ownership guard
    and hands that to *run*. The agents proceed in parallel — their model calls
    overlap at every ``await`` — and a write or shell command that crosses into
    another slice is refused, surfacing as a ``blocked`` step in that agent's
    trace rather than a silently lost edit.

    Returns ``(slice, result)`` pairs in slice order.
    """
    if not slices:
        return []
    root_p = Path(root)
    assert_disjoint(slices, root_p)
    coros: list[Awaitable[AgentResult]] = []
    for i, s in enumerate(slices):
        foreign = tuple(o for j, t in enumerate(slices) if j != i for o in t.owned)
        guard = combine_guards(
            project_root_guard(root_p), ownership_guard(root_p, s.owned, foreign)
        )
        coros.append(run(s, guard))
    results = await asyncio.gather(*coros)
    return list(zip(slices, results, strict=True))


def agent_runner(
    *,
    tier: Tier,
    registry: ToolRegistry,
    sink: MetricsSink,
    task_id: str,
    **run_agent_kwargs: object,
) -> RunSlice:
    """Bind :func:`run_agent` into a :data:`RunSlice` for :func:`run_parallel`.

    Each slice runs the real loop with a per-slice ``task_id`` (so its boundary
    records are attributable in the one trace) under the coordinator's *guard*.
    The *registry* is shared safely — dispatch is stateless and the guard, not the
    toolset, is what differs per agent. Extra keyword args (``preamble``,
    ``max_turns``, ``tier``-fallback, ``on_step`` …) pass straight through.
    """

    async def run(s: Slice, guard: Guard) -> AgentResult:
        sub_id = f"{task_id}:{s.label}" if s.label else task_id
        return await run_agent(
            s.task,
            tier=tier,
            registry=registry,
            sink=sink,
            task_id=sub_id,
            guard=guard,
            **run_agent_kwargs,  # type: ignore[arg-type]
        )

    return run
