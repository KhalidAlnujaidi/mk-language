"""Tests for DeepEval cheats harvested into the eval store.

Covers:
  - Cheat #1: score-aware verdict detects partial regressions
  - Cheat #2: cost/token impact recorded in evolution artifacts
"""

from __future__ import annotations

import json
from pathlib import Path

from evals.runner import EvalReport
from evals.store import _verdict, record_evolution

# ---------------------------------------------------------------------------
# Cheat #1: Score-aware verdict
# ---------------------------------------------------------------------------


def test_verdict_detects_hard_regression() -> None:
    """Fail count increase → regressed (original behavior, unchanged)."""
    before = EvalReport(total=10, passed=10, failed=0)
    after = EvalReport(total=10, passed=9, failed=1)
    assert _verdict(before, after) == "regressed"


def test_verdict_detects_same_count_task_swap_as_regressed() -> None:
    """Same failure count, but a previously-passing task now fails → regressed."""
    before = EvalReport(total=10, passed=9, failed=1, failed_ids=("task-A",))
    after = EvalReport(total=10, passed=9, failed=1, failed_ids=("task-B",))
    assert _verdict(before, after) == "regressed"


def test_verdict_detects_partial_regression_via_score() -> None:
    """Score drop with stable pass/fail → score_regressed (cheat #1)."""
    before = EvalReport(total=10, passed=10, failed=0)
    after = EvalReport(total=10, passed=10, failed=0)
    # Same pass/fail, but score dropped from 0.9 to 0.6
    result = _verdict(before, after, before_score=0.9, after_score=0.6)
    assert result == "score_regressed"


def test_verdict_improved_when_score_rises() -> None:
    """Score increase with stable fails → improved (not score_regressed)."""
    before = EvalReport(total=10, passed=8, failed=2)
    after = EvalReport(total=10, passed=10, failed=0)
    assert _verdict(before, after, before_score=0.7, after_score=0.9) == "improved"


def test_verdict_unchanged_when_scores_equal() -> None:
    """Equal scores and pass/fail → unchanged."""
    before = EvalReport(total=10, passed=10, failed=0)
    after = EvalReport(total=10, passed=10, failed=0)
    assert _verdict(before, after, before_score=0.8, after_score=0.8) == "unchanged"


def test_verdict_unchanged_without_scores() -> None:
    """No scores provided → unchanged (backward compat)."""
    before = EvalReport(total=10, passed=10, failed=0)
    after = EvalReport(total=10, passed=10, failed=0)
    assert _verdict(before, after) == "unchanged"


# ---------------------------------------------------------------------------
# Cheat #1 + #2: Evolution artifact carries score + cost data
# ---------------------------------------------------------------------------


def test_record_evolution_includes_score_data(tmp_path: Path) -> None:
    """Artifact includes before/after/delta score (cheat #1)."""
    before = EvalReport(total=10, passed=10, failed=0)
    after = EvalReport(total=10, passed=10, failed=0)
    record_evolution(
        tmp_path, "ev-score", "feat/score-test", before, after,
        before_score=0.9, after_score=0.7,
    )
    data = json.loads((tmp_path / "ev-score.json").read_text())
    assert data["score"]["before"] == 0.9
    assert data["score"]["after"] == 0.7
    assert data["score"]["delta"] == pytest_approx(-0.2)


def test_record_evolution_includes_cost_data(tmp_path: Path) -> None:
    """Artifact includes before/after/delta cost (cheat #2)."""
    before = EvalReport(total=10, passed=10, failed=0)
    after = EvalReport(total=10, passed=10, failed=0)
    record_evolution(
        tmp_path, "ev-cost", "feat/cost-test", before, after,
        before_cost_usd=0.05, after_cost_usd=0.03,
        before_tokens=5000, after_tokens=3000,
    )
    data = json.loads((tmp_path / "ev-cost.json").read_text())
    assert data["cost"]["before_usd"] == 0.05
    assert data["cost"]["after_usd"] == 0.03
    assert data["cost"]["delta_usd"] == pytest_approx(-0.02)
    assert data["cost"]["before_tokens"] == 5000
    assert data["cost"]["after_tokens"] == 3000
    assert data["cost"]["delta_tokens"] == -2000


def test_record_evolution_verdict_uses_score_for_partial_regression(
    tmp_path: Path,
) -> None:
    """Partial regression detected in the artifact verdict (cheat #1)."""
    before = EvalReport(total=10, passed=10, failed=0)
    after = EvalReport(total=10, passed=10, failed=0)
    record_evolution(
        tmp_path, "ev-partial", "feat/risky-quality", before, after,
        before_score=0.92, after_score=0.55,
    )
    data = json.loads((tmp_path / "ev-partial.json").read_text())
    assert data["verdict"] == "score_regressed"


def test_record_evolution_cost_defaults_to_zero(tmp_path: Path) -> None:
    """Cost fields default to 0 when not provided (backward compat)."""
    before = EvalReport(total=10, passed=10, failed=0)
    after = EvalReport(total=10, passed=10, failed=0)
    record_evolution(tmp_path, "ev-defaults", "feat/test", before, after)
    data = json.loads((tmp_path / "ev-defaults.json").read_text())
    assert data["cost"]["before_usd"] == 0.0
    assert data["cost"]["after_usd"] == 0.0
    assert data["cost"]["delta_tokens"] == 0


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------


def pytest_approx(expected: float, tol: float = 1e-6) -> float:
    """Simple float comparison helper (avoids importing pytest just for approx)."""
    class _Approx:
        def __init__(self) -> None:
            self.expected = expected
            self.tol = tol

        def __eq__(self, other: object) -> bool:
            return isinstance(other, (int, float)) and abs(other - expected) < tol

        def __repr__(self) -> str:
            return f"~{expected}±{tol}"

    return _Approx()  # type: ignore[return-value]
