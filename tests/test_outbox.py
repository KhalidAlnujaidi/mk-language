"""Agent outbox (vision hard truth #4).

Every intended effect is written to a durable, append-only log BEFORE execution,
so it triples as crash-replay source, audit trail, and correction signal. Status
transitions are event-sourced (a new record appended), so history is never
rewritten.
"""

from __future__ import annotations

from pathlib import Path

from daemon.outbox import Outbox


def test_append_then_mark_done_roundtrips(tmp_path: Path):
    box = Outbox(tmp_path / "outbox.jsonl")
    entry = box.append(id="a1", kind="shell", payload="ls -la")
    assert entry.status == "pending"
    box.mark_done("a1")
    latest = {e.id: e for e in box.all()}
    assert latest["a1"].status == "done"
    assert latest["a1"].kind == "shell"
    assert latest["a1"].payload == "ls -la"


def test_pending_returns_only_unfinished(tmp_path: Path):
    box = Outbox(tmp_path / "outbox.jsonl")
    box.append(id="a1", kind="edit", payload="f1")
    box.append(id="a2", kind="edit", payload="f2")
    box.mark_done("a1")
    pending_ids = {e.id for e in box.pending()}
    assert pending_ids == {"a2"}  # the crash-replay set


def test_mark_failed_is_terminal_and_not_pending(tmp_path: Path):
    box = Outbox(tmp_path / "outbox.jsonl")
    box.append(id="a1", kind="tool", payload="call")
    box.mark_failed("a1")
    assert box.pending() == []
    assert {e.id: e.status for e in box.all()}["a1"] == "failed"


def test_history_is_append_only(tmp_path: Path):
    path = tmp_path / "outbox.jsonl"
    box = Outbox(path)
    box.append(id="a1", kind="shell", payload="x")
    box.mark_done("a1")
    # the original pending record is still on disk — history never rewritten
    lines = path.read_text().strip().splitlines()
    assert len(lines) == 2
    assert '"status": "pending"' in lines[0]
    assert '"status": "done"' in lines[1]
