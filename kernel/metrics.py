"""Append-only EventRecord sink.

One JSONL file, one record per line, never rewritten. Honest observability
requires that we never mutate history — only append. Reads reconstruct
``EventRecord`` objects round-trip-exactly including ``tokens_exact`` and
``correction_of``.
"""

from __future__ import annotations

import dataclasses
import json
from pathlib import Path

from kernel.contracts import EventRecord


class MetricsSink:
    """Append-only sink that serialises ``EventRecord`` objects to a JSONL file."""

    def __init__(self, path: Path) -> None:
        self._path = path

    def record(self, event: EventRecord) -> None:
        """Append exactly one JSON line to the file, creating parent dirs if absent."""
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with self._path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(dataclasses.asdict(event)) + "\n")

    def read_all(self) -> list[EventRecord]:
        """Parse every line back into ``EventRecord``. Returns ``[]`` if file absent."""
        if not self._path.exists():
            return []
        records: list[EventRecord] = []
        for line in self._path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                records.append(EventRecord(**json.loads(line)))
        return records

    def last(self) -> EventRecord | None:
        """The most recently recorded event, or ``None`` if empty/absent."""
        all_records = self.read_all()
        return all_records[-1] if all_records else None


class NullSink:
    """A sink that discards all events. Useful for tests or when persistence is not needed."""
    
    def record(self, event: EventRecord) -> None:
        pass

    def read_all(self) -> list[EventRecord]:
        return []

    def last(self) -> EventRecord | None:
        return None
