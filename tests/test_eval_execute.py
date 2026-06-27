"""The golden-set executor — runs the declarative tasks against real components.

Proves the wiring (vision §8.3): every ``evals/tasks/*.json`` case now executes
against the live kinox components and is checked, the runner aggregates them into
an ``EvalReport``, and behaviors we have verified true actually pass. We do NOT
assert the whole set is green — a failing golden task is an honest fitness gap,
not a test failure.
"""

from __future__ import annotations

from pathlib import Path

from evals.execute import run_golden_set, run_task
from evals.runner import run_golden_eval
from evals.schema import load_all_tasks

_ROOT = Path(__file__).resolve().parent.parent
_TASKS = _ROOT / "evals" / "tasks"


def test_every_task_runs_without_raising() -> None:
    n_tasks = len(load_all_tasks(_TASKS))
    results = run_golden_set(_TASKS, root=_ROOT)
    # One result per task file (count is not hardcoded — the golden set grows).
    assert len(results) == n_tasks
    assert n_tasks >= 20  # the golden set is substantial (vision §8.3: 20–50)
    for r in results:
        assert r.assertion_results  # every task produced at least one check
        assert r.duration_ms >= 0.0


def test_run_golden_eval_reports_all_tasks() -> None:
    n_tasks = len(load_all_tasks(_TASKS))
    report = run_golden_eval(_TASKS, root=_ROOT)
    assert report.total == n_tasks
    assert report.passed + report.failed == n_tasks


def _result(task_id: str):
    task = next(t for t in load_all_tasks(_TASKS) if t.id == task_id)
    return run_task(task, root=_ROOT)


def test_known_true_behaviors_pass() -> None:
    # Verified-true behaviors backed by real components — these MUST pass.
    assert _result("redact-api-key").passed  # groom really redacts the key
    assert _result("router-deterministic-redact").passed  # secret → deterministic
    assert _result("groom-tag-intent").passed  # "unittest" → test tag
    assert _result("guard-refuse-rm-rf").passed  # bash guard refuses rm -rf /


def test_guard_leaked_key_passes_only_because_redaction_works() -> None:
    # The secret must not survive into the response_text proxy.
    res = _result("guard-leaked-api-key")
    assert res.passed
    assert "sk-ant-api-1234567890abcdef" not in res.assertion_results[0].actual
