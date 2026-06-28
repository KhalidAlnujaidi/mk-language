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
from kernel.manifest import Manifest

_ROOT = Path(__file__).resolve().parent.parent
_TASKS = _ROOT / "evals" / "tasks"


@pytest.fixture(autouse=True)
def _no_local_model(monkeypatch: pytest.MonkeyPatch) -> None:
    """Force the no-local-model (CI) path for the real-golden-set tests below, so a
    model-dependent ``judged`` task SKIPS and before/after measurements are
    deterministic — no flaky real judge call inside the gate. (judged's live
    behaviour is covered in test_eval_execute + run_golden_eval with a model.)"""
    no_model = Manifest(
        cpu_count=2,
        ram_gb=8.0,
        gpu_vram_gb=None,
        local_models=(),
        cloud_available=False,
    )
    monkeypatch.setattr("evals.execute.probe", lambda: no_model)


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


def test_gate_rejects_a_same_count_task_swap(tmp_path: Path) -> None:
    # The regression the raw failure COUNT misses: one golden task fixed, another
    # broken, net failures unchanged (1 → 1). The per-task set must still reject it.
    before = EvalReport(total=10, passed=9, failed=1, failed_ids=("task-A",))
    after = EvalReport(total=10, passed=9, failed=1, failed_ids=("task-B",))
    decision = evolve.gate(
        Proposal(target="groom.config", change="swap", kind="config"),
        before=before,
        after=after,
        evolutions_dir=tmp_path,
        eval_id="ev-swap",
    )
    assert not decision.approved and not decision.requires_human
    assert "task-B" in decision.reason  # names the regressed task, not a bare count
    assert "regress" in decision.reason.lower()


def test_gate_approves_a_pure_improvement(tmp_path: Path) -> None:
    # A task FIXED with no new failures → empty regression set → approved.
    before = EvalReport(total=10, passed=8, failed=2, failed_ids=("task-A", "task-B"))
    after = EvalReport(total=10, passed=9, failed=1, failed_ids=("task-A",))
    decision = evolve.gate(
        Proposal(target="groom.config", change="fix", kind="config"),
        before=before,
        after=after,
        evolutions_dir=tmp_path,
        eval_id="ev-fix",
    )
    assert decision.approved and not decision.requires_human


def test_gate_rejects_a_quality_regression_with_pass_fail_unchanged(
    tmp_path: Path,
) -> None:
    # Cheat #1: same pass/fail, same failing set — but the mean assertion score
    # slid (a graduated metric decayed while still passing). Must be rejected.
    before = EvalReport(total=10, passed=10, failed=0, mean_score=0.92)
    after = EvalReport(total=10, passed=10, failed=0, mean_score=0.61)
    decision = evolve.gate(
        Proposal(target="groom.config", change="quality decay", kind="config"),
        before=before,
        after=after,
        evolutions_dir=tmp_path,
        eval_id="ev-quality",
    )
    assert not decision.approved and not decision.requires_human
    assert "quality regressed" in decision.reason


def test_gate_approves_when_score_improves_or_is_stable(tmp_path: Path) -> None:
    up = evolve.gate(
        Proposal(target="groom.config", change="improves", kind="config"),
        before=EvalReport(total=10, passed=10, failed=0, mean_score=0.70),
        after=EvalReport(total=10, passed=10, failed=0, mean_score=0.90),
        evolutions_dir=tmp_path,
        eval_id="ev-up",
    )
    assert up.approved
    # A sub-epsilon dip is float jitter, not a regression.
    jitter = evolve.gate(
        Proposal(target="groom.config", change="noise", kind="config"),
        before=EvalReport(total=5, passed=5, failed=0, mean_score=0.9000),
        after=EvalReport(total=5, passed=5, failed=0, mean_score=0.8999),
        evolutions_dir=tmp_path,
        eval_id="ev-jitter",
    )
    assert jitter.approved


def test_run_evolution_gate_records_mean_scores_in_the_artifact(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import json

    reports = iter(
        [
            EvalReport(total=10, passed=10, failed=0, mean_score=0.80),
            EvalReport(total=10, passed=10, failed=0, mean_score=0.80),
        ]
    )
    monkeypatch.setattr(evolve, "run_golden_eval", lambda *_a, **_k: next(reports))
    run_evolution_gate(
        Proposal(target="groom.config", change="x", kind="config"),
        root=_ROOT,
        apply_change=lambda: None,
        evolutions_dir=tmp_path,
        eval_id="ev-rec",
        tasks_dir=_TASKS,
    )
    artifact = json.loads((tmp_path / "ev-rec.json").read_text())
    assert artifact["score"]["before"] == 0.80  # noqa: PLR2004
    assert artifact["score"]["after"] == 0.80  # noqa: PLR2004


def test_run_evolution_gate_rejects_a_task_swap_end_to_end(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Wiring proof: run_evolution_gate carries failed_ids through to the gate, so a
    # same-count swap (one task fixed, another broken) is rejected by identity.
    reports = iter(
        [
            EvalReport(
                total=28, passed=27, failed=1, failed_ids=("router-fuzzy-local",)
            ),
            EvalReport(
                total=28, passed=27, failed=1, failed_ids=("groom-tag-intent",)
            ),
        ]
    )
    monkeypatch.setattr(evolve, "run_golden_eval", lambda *_a, **_k: next(reports))
    decision = run_evolution_gate(
        Proposal(target="groom.config", change="risky-swap", kind="config"),
        root=_ROOT,
        apply_change=lambda: None,
        evolutions_dir=tmp_path,
        eval_id="ev-swap-e2e",
        tasks_dir=_TASKS,
    )
    assert not decision.approved and not decision.requires_human
    assert "groom-tag-intent" in decision.reason
