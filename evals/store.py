"""Versioned evolution artifact store (vision §6 / §8.3).

Every proposed change is recorded as a branch + an eval diff: the golden-eval
report before and after, a verdict, and whether it passes the merge gate (the
eval set must still be green). Artifacts are append-only JSON under an
``evolutions/`` directory, so the history of what was tried — and what it did to
behavior — is durable and auditable.

DeepEval cheat #1 (scored metrics) harvested: ``_verdict`` now detects
*partial regressions* — when the mean assertion score dropped even though
pass/fail counts didn't change. This catches quality decay (0.9→0.6) that
the original boolean delta is blind to.

DeepEval cheat #2 (cost + token accounting) harvested: the artifact now
optionally carries cost/token totals, so the evolution trail records the
cost impact of every proposed change — not just the behavioral impact.
"""

from __future__ import annotations

import dataclasses
import json
from pathlib import Path

from evals.runner import EvalReport


def _verdict(
    before: EvalReport,
    after: EvalReport,
    *,
    before_score: float = 0.0,
    after_score: float = 0.0,
) -> str:
    """Classify the behavioral delta of a change.

    Cheat #1 (scored metrics): if scores are provided, a partial regression
    (score dropped but pass/fail didn't) returns ``"score_regressed"`` —
    a new verdict that signals quality decay the boolean delta misses.

    Order of precedence:
    1. ``regressed``     — fail count increased (hard regression)
    2. ``score_regressed`` — fail count stable but mean score dropped (cheat #1)
    3. ``improved``      — pass count increased, fails stable or down
    4. ``unchanged``     — no movement
    """
    if after.failed > before.failed:
        return "regressed"
    # Cheat #1: detect partial regression via score delta
    if before_score > 0 and after_score < before_score:
        return "score_regressed"
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
    *,
    before_score: float = 0.0,
    after_score: float = 0.0,
    before_cost_usd: float = 0.0,
    after_cost_usd: float = 0.0,
    before_tokens: int = 0,
    after_tokens: int = 0,
) -> Path:
    """Write one evolution artifact and return its path.

    ``gate_passed`` mirrors ``after.ok`` — the merge gate requires the eval set
    to be green after the change (vision §6: auto-merge only on eval pass).

    Cheat #1: ``before_score`` / ``after_score`` enable partial-regression
    detection. Pass the mean assertion score across the eval set.

    Cheat #2: ``before_cost_usd`` / ``after_cost_usd`` record the cost impact
    of the change, so the trail shows whether a proposal made things cheaper
    or more expensive — not just whether behavior changed.
    """
    verdict = _verdict(
        before, after,
        before_score=before_score, after_score=after_score,
    )
    artifact = {
        "eval_id": eval_id,
        "branch": branch,
        "notes": notes,
        "before": dataclasses.asdict(before),
        "after": dataclasses.asdict(after),
        "verdict": verdict,
        "gate_passed": after.ok,
        # Cheat #1: scored metrics — partial regression detection
        "score": {
            "before": round(before_score, 4),
            "after": round(after_score, 4),
            "delta": round(after_score - before_score, 4),
        },
        # Cheat #2: cost + token impact of the change
        "cost": {
            "before_usd": round(before_cost_usd, 6),
            "after_usd": round(after_cost_usd, 6),
            "delta_usd": round(after_cost_usd - before_cost_usd, 6),
            "before_tokens": before_tokens,
            "after_tokens": after_tokens,
            "delta_tokens": after_tokens - before_tokens,
        },
    }
    path = Path(evolutions_dir) / f"{eval_id}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(artifact, indent=2), encoding="utf-8")
    return path
