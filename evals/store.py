"""Versioned evolution artifact store (vision §6 / §8.3).

Every proposed change is recorded as a branch + an eval diff: the golden-eval
report before and after, a verdict, and whether it passes the merge gate (the
eval set must still be green). Artifacts are append-only JSON under an
``evolutions/`` directory, so the history of what was tried — and what it did to
behavior — is durable and auditable.
"""

from __future__ import annotations

import dataclasses
import json
from pathlib import Path

from evals.runner import EvalReport


def _verdict(before: EvalReport, after: EvalReport) -> str:
    """Classify the behavioral delta of a change."""
    if after.failed > before.failed:
        return "regressed"
    if after.passed > before.passed and after.failed <= before.failed:
        return "improved"
    return "unchanged"


def record_evolution(
    evolutions_dir: str | Path,
    eval_id: str,
    branch: str,
    before: EvalReport,
    after: EvalReport,
    notes: str = "",
) -> Path:
    """Write one evolution artifact and return its path.

    ``gate_passed`` mirrors ``after.ok`` — the merge gate requires the eval set
    to be green after the change (vision §6: auto-merge only on eval pass).
    """
    artifact = {
        "eval_id": eval_id,
        "branch": branch,
        "notes": notes,
        "before": dataclasses.asdict(before),
        "after": dataclasses.asdict(after),
        "verdict": _verdict(before, after),
        "gate_passed": after.ok,
    }
    path = Path(evolutions_dir) / f"{eval_id}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(artifact, indent=2), encoding="utf-8")
    return path
