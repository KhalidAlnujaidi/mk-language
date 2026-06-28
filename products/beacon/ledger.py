"""The Beacon ledger — an append-only JSONL record of everything the loop does.

One file, one JSON object per line, never rewritten (the same honest-observability
discipline as ``kernel.metrics.MetricsSink``). The harness writes; the dashboard
reads. Event ``kind`` is one of:

  - ``pledge``     — the loop affirmed the kinox axioms + named its Bible.
  - ``cycle``      — one evolution turn started (cycle index, target challenge).
  - ``finding``    — a KEPT evolution: benefit produced (highlighted green).
  - ``pitfall``    — a rejection / regression / error, with its cause (documented).
  - ``corpus_hit`` — the AIOS Bible was consulted and a finding was reused.
  - ``health``     — per-cycle fleet vitals (tok/s, latency, corpus size, uptime).
  - ``resume``     — a restarted loop picked up where the ledger left off.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

KINDS = ("pledge", "cycle", "finding", "pitfall", "corpus_hit", "health", "resume")


class Ledger:
    """Append-only JSONL event log. Reads degrade gracefully over partial lines."""

    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def record(
        self, kind: str, *, ts: float | None = None, **data: Any
    ) -> dict[str, Any]:
        """Append one event; returns the row written. ``ts`` defaults to now."""
        row: dict[str, Any] = {
            "kind": kind,
            "ts": ts if ts is not None else time.time(),
        }
        row.update(data)
        with self.path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(row) + "\n")
        return row

    def read(self) -> list[dict[str, Any]]:
        """Every event, in order. ``[]`` if absent. Bad lines are skipped."""
        if not self.path.exists():
            return []
        rows: list[dict[str, Any]] = []
        for line in self.path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue
        return rows

    def tail(self, kind: str | None = None, n: int = 50) -> list[dict[str, Any]]:
        """The last *n* events, optionally filtered to one *kind* (newest last)."""
        rows = self.read()
        if kind is not None:
            rows = [r for r in rows if r.get("kind") == kind]
        return rows[-n:]

    def count(self, kind: str) -> int:
        """How many events of *kind* have been recorded."""
        return sum(1 for r in self.read() if r.get("kind") == kind)


@dataclass(frozen=True)
class ResumeState:
    """Where a restarted loop should pick up — recovered from the ledger alone.

    The 24/7 beacon's *durable* state (kept skills, the ledger itself) already
    survives a restart; only the loop's in-memory counters were lost, so a fresh
    process replayed from ``cycle 0`` and reset its uptime — duplicating cycle
    numbers in the append-only history the dashboard reads. Rather than add a new
    store (the kept-skills corpus and ledger are already the durable record), we
    *recycle* the ledger: it already carries everything needed to resume.
    """

    #: The next cycle index to run. One past the highest index ever written, so
    #: no cycle number is ever reused — even one whose cycle started but crashed
    #: before recording ``health``.
    cycle: int
    #: Consecutive non-``kept`` cycles already behind us — replays the loop's idle
    #: rule so a resumed loop keeps backing off instead of re-thrashing.
    idle_streak: int
    #: Seconds the loop had already accrued before this restart, so ``uptime_s``
    #: continues monotonically across restarts instead of resetting to zero.
    uptime_offset: float


def resume_state(ledger: Ledger) -> ResumeState:
    """Reconstruct loop state from the ledger so a restart resumes, not restarts.

    Pure and deterministic (thesis #1): the append-only ledger is ground truth, so
    this needs no model, network, or extra storage. An empty/absent ledger yields
    ``ResumeState(0, 0, 0.0)`` — identical to a cold start, so first boot is
    unchanged and the resume path is fail-soft.

    ``idle_streak`` is replayed from the trailing run of non-``kept`` ``health``
    rows (the live rule is ``0 if kept else streak + 1``). A cycle that crashed
    records a ``pitfall`` but no ``health``, so it can undercount the streak by one
    — harmless: the worst case is one extra busy cycle before idling resumes.
    """
    rows = ledger.read()
    seen = [
        r["cycle"]
        for r in rows
        if r.get("kind") in ("cycle", "health") and isinstance(r.get("cycle"), int)
    ]
    next_cycle = (max(seen) + 1) if seen else 0

    health = [r for r in rows if r.get("kind") == "health"]
    uptime_offset = 0.0
    idle_streak = 0
    if health:
        last_uptime = health[-1].get("uptime_s")
        if isinstance(last_uptime, (int, float)):
            uptime_offset = float(last_uptime)
        for row in reversed(health):
            if row.get("decision") == "kept":
                break
            idle_streak += 1

    return ResumeState(
        cycle=next_cycle, idle_streak=idle_streak, uptime_offset=uptime_offset
    )
