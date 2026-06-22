"""Agent outbox — durable pre-execution action log (vision hard truth #4).

"Every intended file edit / shell command / tool call is written to a durable
log *before* execution. On crash it is the replay source; on success the audit
trail; on correction the free quality label." One structure, three payoffs.

Append-only via event sourcing: ``append`` writes a ``pending`` record;
``mark_done`` / ``mark_failed`` append a fresh terminal record for the same id.
Current state is the fold (last record wins per id), so on-disk history is never
rewritten — the ``pending`` line survives a later ``done`` and remains a faithful
replay/audit source.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, replace
from pathlib import Path

_PENDING = "pending"
_TERMINAL = frozenset({"done", "failed"})


@dataclass(frozen=True)
class OutboxEntry:
    """One intended effect. ``status`` is ``pending`` | ``done`` | ``failed``."""

    id: str
    kind: str
    payload: str
    status: str


class Outbox:
    """Append-only JSONL outbox; state is the per-id fold of its records."""

    def __init__(self, path: Path) -> None:
        self._path = path

    def _write(self, entry: OutboxEntry) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with self._path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(asdict(entry)) + "\n")

    def _records(self) -> list[OutboxEntry]:
        if not self._path.exists():
            return []
        records: list[OutboxEntry] = []
        for line in self._path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                records.append(OutboxEntry(**json.loads(line)))
        return records

    def _latest(self) -> dict[str, OutboxEntry]:
        """Most recent record per id, preserving first-seen insertion order."""
        latest: dict[str, OutboxEntry] = {}
        for rec in self._records():
            latest[rec.id] = rec
        return latest

    def append(self, *, id: str, kind: str, payload: str) -> OutboxEntry:
        """Record a new intended effect as ``pending`` and return it."""
        entry = OutboxEntry(id=id, kind=kind, payload=payload, status=_PENDING)
        self._write(entry)
        return entry

    def _transition(self, id: str, status: str) -> None:
        current = self._latest().get(id)
        if current is None:
            raise KeyError(f"no outbox entry with id {id!r}")
        self._write(replace(current, status=status))

    def mark_done(self, id: str) -> None:
        """Append a terminal ``done`` record for *id*."""
        self._transition(id, "done")

    def mark_failed(self, id: str) -> None:
        """Append a terminal ``failed`` record for *id*."""
        self._transition(id, "failed")

    def all(self) -> list[OutboxEntry]:
        """Current state: the latest record per id, in first-seen order."""
        return list(self._latest().values())

    def pending(self) -> list[OutboxEntry]:
        """Entries not yet in a terminal state — the crash-replay set."""
        return [e for e in self._latest().values() if e.status not in _TERMINAL]
