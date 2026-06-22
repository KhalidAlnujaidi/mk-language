"""The §8.3 versioned artifact store: each evolution = branch + eval diff + verdict."""

import json

from evals.runner import EvalReport
from evals.store import record_evolution


def test_record_evolution_writes_artifact_and_improved_verdict(tmp_path):
    before = EvalReport(total=10, passed=8, failed=2)
    after = EvalReport(total=10, passed=10, failed=0)
    path = record_evolution(
        tmp_path, "ev-1", "feat/fix-redact", before, after, notes="fixed two"
    )

    assert path.exists()
    data = json.loads(path.read_text())
    assert data["eval_id"] == "ev-1"
    assert data["branch"] == "feat/fix-redact"
    assert data["verdict"] == "improved"
    assert data["gate_passed"] is True
    assert data["before"]["failed"] == 2
    assert data["after"]["failed"] == 0


def test_record_evolution_flags_regression_and_fails_gate(tmp_path):
    before = EvalReport(total=10, passed=10, failed=0)
    after = EvalReport(total=10, passed=9, failed=1)
    path = record_evolution(tmp_path, "ev-2", "feat/risky", before, after)

    data = json.loads(path.read_text())
    assert data["verdict"] == "regressed"
    assert data["gate_passed"] is False
