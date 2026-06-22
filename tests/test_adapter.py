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


def test_correction_record_has_unique_task_id(tmp_path: Path) -> None:
    """Fix 1: the correction boundary record must have its OWN unique task_id.

    Specifically:
    - correction_record.correction_of == prior_tag.task_id
    - correction_record.task_id != prior_tag.task_id
    - correction_record.task_id != current_prompt's own tag record task_id
    - all three task_ids in the tag events are distinct
    """
    sink = MetricsSink(tmp_path / "e.jsonl")
    # First prompt — produces the prior tag.
    handle({"prompt": "use postgres"}, cwd=tmp_path, sink=sink, last_prompt=None)
    tag_events_after_first = [e for e in sink.read_all() if e.kind == "tag"]
    assert len(tag_events_after_first) == 1
    prior_tag_id = tag_events_after_first[0].task_id

    # Second prompt — a correction — produces its own tag + a correction record.
    res = handle(
        {"prompt": "no, use sqlite"},
        cwd=tmp_path,
        sink=sink,
        last_prompt="use postgres",
    )
    assert res.was_correction is True

    tag_events = [e for e in sink.read_all() if e.kind == "tag"]
    # We now have 3 tag records: prior tag, current prompt's tag, correction boundary.
    assert len(tag_events) == 3  # noqa: PLR2004

    # Identify the correction record.
    correction_records = [e for e in tag_events if e.correction_of is not None]
    assert len(correction_records) == 1
    correction_rec = correction_records[0]

    # correction_of points to the PRIOR tag.
    assert correction_rec.correction_of == prior_tag_id

    # All three task_ids must be distinct — no two records share an id.
    all_ids = [e.task_id for e in tag_events]
    assert len(set(all_ids)) == 3  # noqa: PLR2004
