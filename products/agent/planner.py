"""A cheap local **prehook planner** that steers the expensive brain.

The agent loop stops fail-CLOSED at ``max_turns`` (``loop.py``). The limit is
deterministic; whether the model *converges* under it is not — a brain that
wanders (re-reads, re-plans) burns the budget. The loop already fights that
*during* the run (read-dedup, a one-shot context nudge), but nothing shapes the
run *before* the expensive model starts.

This module is that missing front-load: a small **local** model (vision §3
thesis #1 — cheap cognition stays local, the dear model is spent only on the hard
part) produces a terse plan *once*, which the loop injects as a **hint, not a
contract**. The guards and the coordinator remain authoritative, so a wrong plan
can mislead but never override safety. It **fails soft** (thesis #2): no planner,
an unavailable model, or an empty answer all yield ``None`` and the brain simply
runs unguided — exactly as before. The planner is never the brain and never has
tools; it only drafts.

Override (env): ``KINOX_PLANNER`` names the planner model (``off`` / ``none`` /
empty disables it); ``KINOX_PLANNER_BACKEND`` / ``KINOX_PLANNER_WHERE`` say where
it is served (default the local Ollama backend). A reasoning finetune that opens
with a ``<think>…</think>`` block is fine — :func:`_strip_think` drops it so only
the plan is injected.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

from daemon.exec import BackendError, Call, ChainExhausted, Messages, execute
from kernel.contracts import Location, Tier
from kernel.metrics import MetricsSink

#: Default planner: ``qwen2.5:7b`` — a fast local *instruct* model. A planner wants
#: to emit a terse checklist quickly, NOT to reason at length: in a head-to-head a
#: reasoning finetune (Qwythos-9B / deepseek-r1) was slow and unreliable here —
#: it burned tens of seconds, hallucinated commands, or (under Ollama 0.30.x's
#: reasoning-field split) left an empty answer — while qwen2.5:7b produced clean,
#: correct plans in ~12s. The model is overridable via ``KINOX_PLANNER``.
DEFAULT_PLANNER_MODEL = "qwen2.5:7b"
DEFAULT_PLANNER_BACKEND = "ollama"
DEFAULT_PLANNER_WHERE: Location = "local"

#: Directories that are noise to a planner — VCS, caches, virtualenvs. Skipped when
#: building the scope file tree so the model sees source, not scratch.
_SKIP_DIRS = frozenset(
    {
        ".git",
        "__pycache__",
        ".venv",
        "node_modules",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        ".cache",
    }
)

#: ``KINOX_PLANNER`` values (case-insensitive) that mean "no prehook planner".
_DISABLE = frozenset({"", "off", "none"})

#: A reasoning model emits its chain-of-thought inside ``<think>…</think>`` — that
#: is scratch, not the plan, so it is stripped before injection.
_THINK = re.compile(r"<think>.*?</think>", re.DOTALL | re.IGNORECASE)

_PLANNER_SYSTEM = (
    "You are a planning prehook for a coding agent. Given a task — and, when "
    "provided, the list of files in scope — emit a SHORT ordered checklist (at "
    "most 6 steps) of concrete actions, naming the REAL files or directories each "
    "step touches (use the provided file list; never invent paths). Bound the "
    "scope tightly — fewer, sharper steps beat exhaustive ones. Do NOT execute "
    "anything, do NOT explain, do NOT ask questions. Output the checklist one step "
    "per line, then a final line 'Done when: <observable condition>' stating how "
    "the agent knows the task is finished, so it stops instead of over-working."
)


def planner_tier() -> Tier | None:
    """The prehook planner tier — a cheap local model, or ``None`` if disabled.

    Returns ``None`` when ``KINOX_PLANNER`` is set to a disabling value
    (``off`` / ``none`` / empty), so the caller skips planning and the brain runs
    unguided (fail-soft). Otherwise the model/where/backend come from the
    ``KINOX_PLANNER*`` env, defaulting to Qwythos-9B on the local Ollama backend.
    """
    name = os.environ.get("KINOX_PLANNER", DEFAULT_PLANNER_MODEL)
    if name.strip().lower() in _DISABLE:
        return None
    backend = os.environ.get("KINOX_PLANNER_BACKEND", DEFAULT_PLANNER_BACKEND)
    where_env = os.environ.get("KINOX_PLANNER_WHERE", DEFAULT_PLANNER_WHERE)
    where: Location = (
        where_env if where_env in ("local", "cloud") else DEFAULT_PLANNER_WHERE
    )
    return Tier.model(name, where=where, backend=backend)


def _strip_think(text: str) -> str:
    """Drop ``<think>…</think>`` reasoning blocks, leaving only the plan."""
    return _THINK.sub("", text).strip()


def _scope_tree(root: Path, *, max_entries: int = 150, max_depth: int = 2) -> str:
    """A compact, shallow listing of *root*'s files — enough to ground the planner
    in real paths without flooding its context.

    Walks at most *max_depth* levels, skips VCS/cache/virtualenv noise and hidden
    entries, and caps at *max_entries* (a planner needs orientation, not a full
    inventory). Returns relative POSIX paths, one per line; empty if *root* has no
    listable files. Read-only — listing never crosses the scope's write wall.
    """
    root = Path(root)
    lines: list[str] = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(
            d for d in dirnames if d not in _SKIP_DIRS and not d.startswith(".")
        )
        rel = Path(dirpath).relative_to(root)
        if len(rel.parts) >= max_depth:
            dirnames[:] = []  # prune deeper descent, keep this level's files
        for f in sorted(filenames):
            if f.startswith("."):
                continue
            lines.append((rel / f).as_posix() if rel.parts else f)
            if len(lines) >= max_entries:
                lines.append("… (more files omitted)")
                return "\n".join(lines)
    return "\n".join(lines)


def _default_plan_call() -> Call:
    """The production planner call: a plain chat dispatch with **no tools** — the
    planner drafts text, it never acts."""
    from daemon.backends import make_dispatch

    return make_dispatch()


async def plan_task(
    task: str,
    *,
    sink: MetricsSink,
    task_id: str,
    root: Path | None = None,
    tier: Tier | None = None,
    call: Call | None = None,
    registry: Any = None,
) -> str | None:
    """Draft a terse plan for *task* with the cheap local planner, or ``None``.

    Calls the planner model **once** (no tools, no fallback chain) and returns its
    cleaned checklist. Returns ``None`` — so the brain runs unguided — when the
    planner is disabled, the model is unavailable (``BackendError`` /
    ``ChainExhausted``), or the answer is empty after stripping reasoning. Every
    outcome is fail-soft: planning can only help, never block (thesis #2).

    The boundary is recorded on *sink* like any model call (``kind="plan"``) so
    the prehook is visible in the honest action log (vision §4.6), distinct from
    the agent turns it precedes.

    *root*, when given, is the scope directory; a compact shallow listing of its
    files is handed to the planner so it names REAL paths instead of inventing
    them (a blind planner guessed ``kx_cli.py`` for a CLI that lives in ``kx``).
    Listing is read-only and never crosses the scope's write wall.
    """
    planner = tier if tier is not None else planner_tier()
    if planner is None:
        return None
    plan_call = call if call is not None else _default_plan_call()
    # Ground the plan in real paths: a blind planner invents files (it guessed
    # `kx_cli.py` for a CLI that lives in `kx`); the scope tree fixes that.
    user = task
    
    # NLP Pre-Hooks
    try:
        from products.agent import nlp_hooks
        intent = await nlp_hooks.classify_intent(task)
        if intent == "answering a question":
            # Questions don't need a multi-step execution plan touching files
            return None
            
        summary = await nlp_hooks.summarize_context(task)
        if summary:
            user = f"Context Summary:\n{summary}\n\nTask: {user}"
            
        if registry is not None:
            top_skills = await nlp_hooks.retrieve_skills(task, registry)
            if top_skills:
                skills_str = "\n".join(top_skills)
                user = f"Relevant Skills:\n{skills_str}\n\n{user}"
    except Exception:
        pass  # Fail soft if NLP hooks fail

    if root is not None:
        tree = _scope_tree(root)
        if tree:
            user = (
                f"Files in scope (use these real paths, never invent):\n{tree}"
                f"\n\nTask:\n{user}"
            )
    messages: Messages = [
        {"role": "system", "content": _PLANNER_SYSTEM},
        {"role": "user", "content": user},
    ]
    try:
        result = await execute(
            [planner], messages, call=plan_call, task_id=task_id, kind="plan"
        )
    except (BackendError, ChainExhausted):
        return None  # fail soft: the brain runs without a plan
    # The prehook is an auditable boundary like any model call (vision §4.6).
    sink.record(result.event)
    plan = _strip_think(result.content)
    return plan or None
