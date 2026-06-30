"""The generative run-output model (vision §5.2 Layer 3 — generative/TUI output).

Pure, render-agnostic: an ``AgentResult`` in, a structured ``RunView`` out. These
prove the view is composed faithfully from the run's structure — the answer, the
per-tool tally, the trace steps, the footer — so the TUI renderer is a thin map
over tested data (and the plain fallback loses nothing).
"""

from __future__ import annotations

from products.agent.loop import AgentResult, AgentStep
from products.chat.output import build_run_view, strip_reasoning


def _result(
    *,
    final_text: str = "done",
    turns: int = 2,
    stopped: str = "complete",
    steps: list[AgentStep] | None = None,
) -> AgentResult:
    return AgentResult(
        final_text=final_text, steps=steps or [], turns=turns, stopped=stopped
    )


def test_strip_reasoning_removes_think_blocks() -> None:
    assert strip_reasoning("<think>secret</think>answer") == "answer"
    assert strip_reasoning("<THINKING>x</THINKING>  hi") == "hi"
    assert strip_reasoning("plain text") == "plain text"


def test_footer_format_and_ok_flag() -> None:
    v = build_run_view(_result(turns=3, stopped="complete"), tools=2, elapsed_s=1.44)
    assert v.ok is True
    assert v.footer == "complete · 3 turns · 2 tools · 1.4s"


def test_not_ok_when_stopped_is_not_complete() -> None:
    v = build_run_view(_result(stopped="stuck"), tools=0, elapsed_s=0.0)
    assert v.ok is False
    assert "stuck" in v.footer


def test_tool_tally_counts_blocked_and_order() -> None:
    steps = [
        AgentStep("tool", "read_file", "a"),
        AgentStep("tool", "read_file", "b"),
        AgentStep("blocked", "write_file", "nope"),
        AgentStep("tool", "run_bash", "ls"),
        AgentStep("final", "", "done"),  # the final is never a "tool"
    ]
    v = build_run_view(_result(steps=steps), tools=4, elapsed_s=2.0)
    counts = {tc.name: (tc.count, tc.blocked) for tc in v.tool_counts}
    assert counts == {
        "read_file": (2, 0),
        "write_file": (1, 1),
        "run_bash": (1, 0),
    }
    # ordered by first appearance, and the final turn is excluded
    assert [tc.name for tc in v.tool_counts] == ["read_file", "write_file", "run_bash"]


def test_tool_summary_formatting() -> None:
    steps = [
        AgentStep("tool", "read_file", "a"),
        AgentStep("tool", "read_file", "b"),
        AgentStep("blocked", "write_file", "x"),
    ]
    v = build_run_view(_result(steps=steps), tools=3, elapsed_s=1.0)
    assert v.tool_summary == "read_file×2 · write_file (1 blocked)"


def test_steps_mapped_and_long_detail_truncated() -> None:
    long = "x" * 200
    steps = [AgentStep("tool", "read_file", long), AgentStep("final", "", "ok")]
    v = build_run_view(_result(steps=steps), tools=1, elapsed_s=0.0)
    assert v.steps[0].kind == "tool" and v.steps[0].name == "read_file"
    assert len(v.steps[0].detail) <= 64 and v.steps[0].detail.endswith("…")
    assert v.steps[1].kind == "final"


def test_empty_run_has_blank_tool_summary() -> None:
    v = build_run_view(_result(steps=[]), tools=0, elapsed_s=0.0)
    assert v.tool_summary == ""
    assert v.tool_counts == ()
    assert v.steps == ()
