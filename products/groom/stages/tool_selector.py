"""Stage: tool_selector — capability router to avoid context window clutter.

Thesis #1: fuzzy routing stays local via a capped model.
Thesis #2: fail-direction is SOFT — if the router returns nothing, fall back to
           all tools (empty tuple meaning no restriction).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from kernel.contracts import FailDirection, Task, TaskKind, Tier
from kernel.manifest import Manifest
from kernel.router import route

FAIL_DIRECTION: FailDirection = FailDirection.SOFT

#: A model-backed tool selector: given the routed model tier and the text, return tool names
#: (or ``None`` to decline — the caller then falls soft to no restriction).
ModelSelect = Callable[[Tier, str], "tuple[str, ...] | None"]

# Budget cap for the fuzzy tool selection task (milliseconds).
TOOL_SELECT_BUDGET_MS: int = 500


@dataclass(frozen=True)
class ToolSelectorResult:
    """The result of a tool selection pass. Empty tuple means no restriction (all tools available)."""

    tools: tuple[str, ...]
    tier: Tier


def select(
    text: str, manifest: Manifest, *, model_select: ModelSelect | None = None
) -> ToolSelectorResult:
    """Select required tools for *text*: route for real, offloading to a local model.

    Builds a ``Task(kind=TaskKind.TAG, budget_ms=TOOL_SELECT_BUDGET_MS)`` and asks the
    router which tier to use. When *model_select* is supplied AND the routed tier is
    a model, the selection is offloaded to that model.
    Otherwise, we fall soft to returning an empty tuple (SOFT fail-direction), implying
    all tools remain available.
    """
    # Note: Using TaskKind.TAG to remain within jail rules (kernel/contracts.py is readonly).
    task = Task(kind=TaskKind.TAG, budget_ms=TOOL_SELECT_BUDGET_MS)
    routed: Tier | None = route(task, manifest)
    tier: Tier = routed if routed is not None else Tier.deterministic()

    if model_select is not None and tier.is_model:
        selected_tools = model_select(tier, text)
        if selected_tools is not None:  # none means decline
            return ToolSelectorResult(tools=tuple(selected_tools), tier=tier)

    return ToolSelectorResult(tools=(), tier=tier)
