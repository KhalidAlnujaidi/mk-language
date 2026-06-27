"""The evolution gate driven by the REAL golden eval set (vision §8.3).

Proves the connection the audit found missing: ``run_evolution_gate`` measures the
golden set before/after a proposal (via ``run_golden_eval``) and feeds those real
reports to ``gate`` — so self-evolution is blocked on the golden baseline, not on a
hand-supplied report. Code is never self-applied; a sanctioned config change is
auto-approved only if the golden set does not regress vs. the baseline.
"""

from __future__ import annotations

from pathlib import Path

import evals.evolve as evolve
import pytest
from evals.evolve import Proposal, run_evolution_gate
from evals.runner import EvalReport

_ROOT = Path(__file__).resolve().parent.parent
_TASKS = _ROOT / "evals" / "tasks"


def test_code_proposal_is_human_gated_and_never_applied(tmp_path: Path) -> None:
    applied = {"n": 0}

    def apply() -> None:
        applied["n"] += 1

    decision = run_evolution_gate(
        Proposal(target="kernel.router", change="tweak", kind="code"),
        root=_ROOT,
        apply_change=apply,
        evolutions_dir=tmp_path,
        eval_id="ev-code",
        tasks_dir=_TASKS,
    )
    assert decision.requires_human and not decision.approved
    assert applied["n"] == 0  # code is NEVER self-applied


def test_config_change_with_no_regression_is_approved(tmp_path: Path) -> None:
    # apply_change is a no-op → the golden set is identical before/after → no
    # regression → auto-approved, even though the baseline has known-failing tasks
    # (the bar is "no NEW failures", not "all green").
    applied = {"n": 0}

    def apply() -> None:
        applied["n"] += 1

    decision = run_evolution_gate(
        Proposal(target="groom.config", change="reorder", kind="config"),
        root=_ROOT,
        apply_change=apply,
        evolutions_dir=tmp_path,
        eval_id="ev-config",
        tasks_dir=_TASKS,
    )
    assert decision.approved and not decision.requires_human
    assert applied["n"] == 1  # a sanctioned config change IS applied
    assert (tmp_path / "ev-config.json").exists()  # durable, auditable artifact


def test_config_change_that_regresses_is_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Wire-level proof of the regression branch: before has 5 failures, the after
    # run (post-apply) has 6 → a new failure → rejected. We control the two golden
    # measurements to make the regression deterministic, proving run_evolution_gate
    # feeds before vs. after to the gate correctly.
    reports = iter(
        [
            EvalReport(total=30, passed=25, failed=5),  # before
            EvalReport(total=30, passed=24, failed=6),  # after — regressed
        ]
    )
    monkeypatch.setattr(evolve, "run_golden_eval", lambda *_a, **_k: next(reports))
    decision = run_evolution_gate(
        Proposal(target="groom.config", change="risky", kind="config"),
        root=_ROOT,
        apply_change=lambda: None,
        evolutions_dir=tmp_path,
        eval_id="ev-regress",
        tasks_dir=_TASKS,
    )
    assert not decision.approved and not decision.requires_human
    assert "regress" in decision.reason.lower()
