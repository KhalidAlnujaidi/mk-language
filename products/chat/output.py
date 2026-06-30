"""Generative run-output model (vision §5.2 Layer 3 — generative/TUI output).

Pure presentation logic: turn one agent run (an ``AgentResult``) into a structured
view — the reasoning-stripped answer, a generated trace recap of what the agent
actually did (each tool step + the final), and a one-line summary with a per-tool
tally. No ``rich``, no TTY, fully deterministic and unit-testable.

This is the "generative" part of the UX layer: the view is *composed from the
run's structure* rather than printed ad-hoc, so the TUI renderer
(``products/chat/app.py``) just maps it to panels/trees/glyphs — and can fall
back to plain text without losing any information. Keeping it here (pure) means
the output is testable the way the kernel is.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # avoid importing the agent at module load (cold-start discipline)
    from products.agent.loop import AgentResult

_THINK_RE = re.compile(
    r"<think(?:ing)?>.*?</think(?:ing)?>\s*", re.DOTALL | re.IGNORECASE
)
_MAX_DETAIL = 64
#: AgentStep.kind values we render distinctly; anything else is treated as a tool.
_KNOWN_KINDS = ("tool", "blocked", "final")


def strip_reasoning(text: str) -> str:
    """Drop ``<think>``/``<thinking>`` blocks so a reasoning model's scratchpad
    never leaks into the rendered answer."""
    return _THINK_RE.sub("", text).strip()


def _truncate(text: str, limit: int = _MAX_DETAIL) -> str:
    """Collapse whitespace and clip *text* to *limit* with an ellipsis."""
    flat = " ".join(text.split())
    return flat if len(flat) <= limit else flat[: limit - 1] + "…"


@dataclass(frozen=True)
class StepLine:
    """One line of the generated trace recap. ``kind`` is the AgentStep kind
    (``tool`` | ``blocked`` | ``final``); the renderer maps it to a glyph."""

    kind: str
    name: str
    detail: str


@dataclass(frozen=True)
class ToolCount:
    """How often a tool was called this run, and how often it was blocked."""

    name: str
    count: int
    blocked: int


@dataclass(frozen=True)
class RunView:
    """The structured, render-agnostic view of one agent run."""

    answer: str
    stopped: str
    turns: int
    tools: int
    elapsed_s: float
    ok: bool
    steps: tuple[StepLine, ...]
    tool_counts: tuple[ToolCount, ...]

    @property
    def footer(self) -> str:
        """The one-line status summary: ``complete · 3 turns · 2 tools · 1.4s``."""
        return " · ".join(
            (
                self.stopped,
                f"{self.turns} turns",
                f"{self.tools} tools",
                f"{self.elapsed_s:.1f}s",
            )
        )

    @property
    def tool_summary(self) -> str:
        """A generated per-tool tally, e.g. ``read_file×3 · run_bash · 1 blocked``."""
        bits: list[str] = []
        for tc in self.tool_counts:
            label = tc.name if tc.count == 1 else f"{tc.name}×{tc.count}"
            if tc.blocked:
                label += f" ({tc.blocked} blocked)"
            bits.append(label)
        return " · ".join(bits)


def _step_lines(steps: object) -> tuple[StepLine, ...]:
    out: list[StepLine] = []
    for step in steps or ():  # type: ignore[union-attr]  # duck-typed AgentStep
        kind = step.kind if step.kind in _KNOWN_KINDS else "tool"
        out.append(
            StepLine(kind=kind, name=step.name, detail=_truncate(str(step.detail)))
        )
    return tuple(out)


def _tool_counts(steps: object) -> tuple[ToolCount, ...]:
    order: list[str] = []
    counts: dict[str, int] = {}
    blocked: dict[str, int] = {}
    for step in steps or ():  # type: ignore[union-attr]  # duck-typed AgentStep
        if step.kind == "final":
            continue
        name = step.name or "?"
        if name not in counts:
            counts[name] = 0
            blocked[name] = 0
            order.append(name)
        counts[name] += 1
        if step.kind == "blocked":
            blocked[name] += 1
    return tuple(ToolCount(n, counts[n], blocked[n]) for n in order)


def build_run_view(
    result: AgentResult, *, tools: int, elapsed_s: float
) -> RunView:
    """Compose a :class:`RunView` from a finished agent run (pure)."""
    return RunView(
        answer=strip_reasoning(result.final_text),
        stopped=result.stopped,
        turns=result.turns,
        tools=tools,
        elapsed_s=elapsed_s,
        ok=result.stopped == "complete",
        steps=_step_lines(result.steps),
        tool_counts=_tool_counts(result.steps),
    )
