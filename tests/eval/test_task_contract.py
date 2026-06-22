# swarm-drafted (kinox-swarm-3, Nemotron-14B); curated locally
# Behavioral: the Task contract forces honest budgets — a FUZZY task must cap a
# model call (budget_ms required); a GROUND_TRUTH task calls no model (budget_ms
# forbidden). (Fixed: the draft used module-level asserts that ran at collection
# and contributed 0 pytest tests.)
import pytest
from kernel.contracts import Task, TaskKind


def test_fuzzy_task_requires_budget():
    with pytest.raises(ValueError):
        Task(TaskKind.TAG)  # fuzzy, no budget_ms -> reject


def test_ground_truth_task_forbids_budget():
    with pytest.raises(ValueError):
        Task(TaskKind.REDACT, budget_ms=500)  # ground-truth, no model to cap -> reject


def test_valid_fuzzy_task_constructs():
    task = Task(TaskKind.TAG, budget_ms=500)
    assert task.budget_ms == 500
