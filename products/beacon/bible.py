"""The Bible — AIOS (agiresearch/AIOS) as the loop's state-of-the-art reference.

The cluster agents do not self-develop in a vacuum: before proposing a new
skill, the loop *consults the Bible* — the AIOS corpus (``cheatcodes/AIOS``) of
LLM-agent-OS findings — and feeds the most relevant passage into the proposal as
reference material. A consult that surfaces a passage is recorded as a
``corpus_hit`` (Rule Zero made measurable: reuse a finding instead of inventing).

Retrieval is dependency-light by design — stdlib word-overlap scoring over
markdown chunks, no embeddings, no model. It is deterministic, so it is unit
testable, and it is good enough to pull the on-topic passage for a short
challenge prompt.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

_WORD = re.compile(r"[a-z0-9]+")
_STOP = frozenset(
    [
        "the", "a", "an", "and", "or", "of", "to", "in", "for", "on", "is",
        "are", "be", "with", "that", "this", "it", "as", "by", "from", "at",
        "which", "we", "you", "they", "i", "how", "what", "when", "where",
        "why", "can", "will", "into", "over", "under", "not", "no", "your",
        "their", "our", "its",
    ]
)


def _tokens(text: str) -> set[str]:
    return {w for w in _WORD.findall(text.lower()) if w not in _STOP and len(w) > 2}


@dataclass(frozen=True)
class Passage:
    """One retrievable chunk of the Bible: where it came from and its text."""

    source: str  # path relative to the corpus root
    text: str


class Bible:
    """An indexed, queryable corpus of markdown findings (AIOS by default)."""

    def __init__(
        self, root: Path | str, *, name: str = "AIOS", max_chars: int = 900
    ) -> None:
        self.root = Path(root)
        self.name = name
        self._max_chars = max_chars
        self.passages: list[Passage] = self._index()

    def _index(self) -> list[Passage]:
        """Walk every ``*.md`` under the root, split into paragraph-ish chunks."""
        passages: list[Passage] = []
        if not self.root.is_dir():
            return passages
        for md in sorted(self.root.rglob("*.md")):
            if "/.git/" in str(md):
                continue
            try:
                text = md.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            rel = str(md.relative_to(self.root))
            for block in re.split(r"\n\s*\n", text):
                block = block.strip()
                if len(block) < 40:
                    continue
                passages.append(Passage(source=rel, text=block[: self._max_chars]))
        return passages

    def consult(self, query: str, *, k: int = 2) -> list[Passage]:
        """Top-*k* passages by word overlap with *query* (empty if nothing scores)."""
        q = _tokens(query)
        if not q or not self.passages:
            return []
        scored: list[tuple[int, Passage]] = []
        for p in self.passages:
            overlap = len(q & _tokens(p.text))
            if overlap > 0:
                scored.append((overlap, p))
        scored.sort(key=lambda sp: sp[0], reverse=True)
        return [p for _, p in scored[:k]]

    @property
    def size(self) -> int:
        """Number of indexed passages — the breadth of the Bible."""
        return len(self.passages)
