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

from daemon.exec import BackendError, Call, ChainExhausted, Messages, execute
from kernel.contracts import Location, Tier
from kernel.metrics import MetricsSink

#: Default planner: the Qwythos-9B reasoning finetune (native function-calling,
#: ``<think>``-prefixed CoT) pulled into local Ollama. It only drafts a plan here,
#: so its tool-calling is unused — what matters is terse, structured decomposition.
DEFAULT_PLANNER_MODEL = "hf.co/empero-ai/Qwythos-9B-Claude-Mythos-5-1M-GGUF:Q4_K_M"
DEFAULT_PLANNER_BACKEND = "ollama"
DEFAULT_PLANNER_WHERE: Location = "local"

#: ``KINOX_PLANNER`` values (case-insensitive) that mean "no prehook planner".
_DISABLE = frozenset({"", "off", "none"})

#: A reasoning model emits its chain-of-thought inside ``<think>…</think>`` — that
#: is scratch, not the plan, so it is stripped before injection.
_THINK = re.compile(r"<think>.*?</think>", re.DOTALL | re.IGNORECASE)

_PLANNER_SYSTEM = (
    "You are a planning prehook for a coding agent. Given a task, emit a SHORT "
    "ordered checklist (at most 6 steps) of concrete actions, naming the files or "
    "directories each step touches. Bound the scope tightly — fewer, sharper steps "
    "beat exhaustive ones. Do NOT execute anything, do NOT explain, do NOT ask "
    "questions. Output only the checklist, one step per line."
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
    tier: Tier | None = None,
    call: Call | None = None,
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
    """
    planner = tier if tier is not None else planner_tier()
    if planner is None:
        return None
    plan_call = call if call is not None else _default_plan_call()
    messages: Messages = [
        {"role": "system", "content": _PLANNER_SYSTEM},
        {"role": "user", "content": task},
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
