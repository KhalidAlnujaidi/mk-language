"""Tests for adapters.claude_code — the UserPromptSubmit hook adapter.

TDD Step 1: write these tests first; they must be RED before implementation.
"""

from __future__ import annotations

from pathlib import Path

from adapters.claude_code import handle
from kernel.metrics import MetricsSink


def test_handle_grooms_prompt_into_annotation(tmp_path: Path) -> None:
    sink = MetricsSink(tmp_path / "e.jsonl")
    res = handle(
        {"prompt": "implement a feature"},
        cwd=tmp_path,
        sink=sink,
        last_prompt=None,
    )
    assert res.annotation.is_blocked is False
    assert res.was_correction is False
    assert any("feature" in line for line in res.annotation.lines)


def test_handle_flags_a_correction_and_links_prior_tag(tmp_path: Path) -> None:
    sink = MetricsSink(tmp_path / "e.jsonl")
    handle({"prompt": "use postgres"}, cwd=tmp_path, sink=sink, last_prompt=None)
    res = handle(
        {"prompt": "no, use sqlite"},
        cwd=tmp_path,
        sink=sink,
        last_prompt="use postgres",
    )
    assert res.was_correction is True
    tag_events = [e for e in sink.read_all() if e.kind == "tag"]
    assert any(e.correction_of is not None for e in tag_events)
