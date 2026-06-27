"""The axioms the loop pledges to before it is allowed to self-develop.

Before any cycle, the harness affirms kinox's load-bearing axioms (sourced from
``vision.md``) and names its Bible. The pledge is recorded to the ledger — an
auditable "I will not break things" affirmation that precedes free, autonomous
work. The axioms are not enforcement (the *governance* is structural and lives
in ``products/evolve``); the pledge is the honest, logged statement of intent.
"""

from __future__ import annotations

import re
from pathlib import Path

from products.beacon.ledger import Ledger

#: Always-present core, derived from kinox's own fitness challenges + vision.
#: Used verbatim when ``vision.md`` is missing, and merged with what we extract.
CORE_AXIOMS: tuple[str, ...] = (
    "When a task has a ground truth (regex, AST, git, filesystem), plain "
    "deterministic code does the work — never a model judging a model.",
    "A guard in doubt fails CLOSED; an optimizer in doubt fails SOFT.",
    "Reuse before building (Rule Zero): assume it already exists and prove it "
    "does not first — compose, do not invent.",
    "Honest observability: every boundary is recorded; never fabricate a value, "
    "never leave a silent gap.",
    "Self-improvement is governed by a deterministic verifier the model cannot "
    "see or edit — so noise can only become measured benefit, never breakage.",
)


def load_axioms(vision_path: Path | str) -> list[str]:
    """Extract axiom-like lines from *vision.md*, merged with :data:`CORE_AXIOMS`.

    Best-effort and defensive: a missing/unreadable file just yields the core
    set. We pull lines that read like theses/axioms (mention "thesis", "axiom",
    "fail closed/soft", or "ground truth"), de-duplicated and length-bounded.
    """
    extracted: list[str] = []
    try:
        text = Path(vision_path).read_text(encoding="utf-8")
        pattern = re.compile(
            r"thesis|axiom|fail[- ]?(closed|soft)|ground[- ]?truth", re.I
        )
        for raw in text.splitlines():
            line = raw.strip().lstrip("#->*•0123456789. ").strip()
            if 20 <= len(line) <= 200 and pattern.search(line):
                extracted.append(line)
    except OSError:
        pass

    seen: set[str] = set()
    out: list[str] = []
    for ax in (*CORE_AXIOMS, *extracted):
        key = ax.lower()
        if key not in seen:
            seen.add(key)
            out.append(ax)
    return out


def pledge(
    ledger: Ledger, axioms: list[str], *, bible: str, cycle: int = 0
) -> dict[str, object]:
    """Record (and return) the loop's pledge to *axioms* under its *bible*."""
    return ledger.record(
        "pledge",
        cycle=cycle,
        bible=bible,
        axioms=axioms,
        oath=(
            "I pledge to these axioms before self-developing. I will improve only "
            "through the governed, deterministic verifier and will not break things."
        ),
    )
