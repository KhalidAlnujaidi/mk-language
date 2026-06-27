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
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

KINDS = ("pledge", "cycle", "finding", "pitfall", "corpus_hit", "health")


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
