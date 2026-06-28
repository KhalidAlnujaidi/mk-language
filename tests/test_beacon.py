"""Beacon's deterministic parts, proven without a model or network.

The ledger, the AIOS Bible retrieval, and the axiom pledge are all plain code
with ground truth — so they are tested as plain code (thesis #1). The harness's
governed cycle is exercised live against the cluster, not here.
"""

from __future__ import annotations

from pathlib import Path

from products.beacon.axioms import CORE_AXIOMS, load_axioms, pledge
from products.beacon.bible import Bible
from products.beacon.ledger import Ledger, resume_state


def test_ledger_appends_and_tails(tmp_path: Path) -> None:
    led = Ledger(tmp_path / "l.jsonl")
    led.record("cycle", cycle=0)
    led.record("finding", cycle=0, skill="evolved-x")
    led.record("pitfall", cycle=1, cause="boom")
    assert led.count("finding") == 1
    assert led.count("pitfall") == 1
    assert led.tail("finding")[0]["skill"] == "evolved-x"
    assert [r["kind"] for r in led.read()] == ["cycle", "finding", "pitfall"]


def test_ledger_skips_corrupt_lines(tmp_path: Path) -> None:
    p = tmp_path / "l.jsonl"
    led = Ledger(p)
    led.record("cycle", cycle=0)
    p.write_text(p.read_text() + "{ not json\n", encoding="utf-8")
    assert len(led.read()) == 1  # the bad line is skipped, not fatal


def test_resume_empty_ledger_is_cold_start(tmp_path: Path) -> None:
    state = resume_state(Ledger(tmp_path / "l.jsonl"))
    assert (state.cycle, state.idle_streak, state.uptime_offset) == (0, 0, 0.0)


def test_resume_continues_cycle_uptime_and_idle(tmp_path: Path) -> None:
    led = Ledger(tmp_path / "l.jsonl")
    # Two completed cycles: cycle 0 kept, cycle 1 rejected (idle streak now 1).
    led.record("cycle", cycle=0)
    led.record("health", cycle=0, decision="kept", uptime_s=10.0)
    led.record("cycle", cycle=1)
    led.record("health", cycle=1, decision="rejected:no-improvement", uptime_s=25.0)

    state = resume_state(led)
    assert state.cycle == 2  # next index, never a reused number
    assert state.idle_streak == 1  # trailing non-kept run since the last "kept"
    assert state.uptime_offset == 25.0  # last health uptime → monotonic across boot


def test_resume_counts_full_trailing_idle_run(tmp_path: Path) -> None:
    led = Ledger(tmp_path / "l.jsonl")
    led.record("health", cycle=0, decision="kept", uptime_s=5.0)
    for c in range(1, 4):  # three non-kept cycles after the last keep
        led.record("health", cycle=c, decision="all-pass", uptime_s=5.0 + c)
    assert resume_state(led).idle_streak == 3


def test_resume_advances_past_crashed_cycle_without_health(tmp_path: Path) -> None:
    led = Ledger(tmp_path / "l.jsonl")
    led.record("health", cycle=0, decision="kept", uptime_s=8.0)
    led.record("cycle", cycle=1)  # started then crashed: pitfall, no health
    led.record("pitfall", cycle=1, cause="boom")

    state = resume_state(led)
    assert state.cycle == 2  # crashed cycle's number is not reused
    assert state.uptime_offset == 8.0  # falls back to the last good health uptime


def test_bible_retrieves_relevant_passage(tmp_path: Path) -> None:
    root = tmp_path / "bible"
    root.mkdir()
    (root / "mem.md").write_text(
        "# Memory\n\nThe agent memory manager stores and retrieves context.\n\n"
        "Unrelated paragraph about installation and docker compose files here.\n",
        encoding="utf-8",
    )
    bible = Bible(root, name="AIOS")
    assert bible.size >= 2
    hits = bible.consult("how does the agent memory manager retrieve context?", k=1)
    assert hits and "memory" in hits[0].text.lower()


def test_bible_missing_root_is_empty(tmp_path: Path) -> None:
    bible = Bible(tmp_path / "nope")
    assert bible.size == 0 and bible.consult("anything") == []


def test_axioms_fallback_and_pledge(tmp_path: Path) -> None:
    # Missing vision file → core axioms still returned.
    axioms = load_axioms(tmp_path / "absent.md")
    assert axioms[: len(CORE_AXIOMS)] == list(CORE_AXIOMS)
    led = Ledger(tmp_path / "l.jsonl")
    row = pledge(led, axioms, bible="AIOS", cycle=3)
    assert row["bible"] == "AIOS" and row["cycle"] == 3
    assert led.tail("pledge")[0]["axioms"] == axioms


def test_axioms_extracts_from_vision(tmp_path: Path) -> None:
    v = tmp_path / "vision.md"
    v.write_text(
        "## Theses\n- thesis #1: ground truth means deterministic code wins.\n",
        encoding="utf-8",
    )
    axioms = load_axioms(v)
    assert any("ground truth means deterministic" in a.lower() for a in axioms)
