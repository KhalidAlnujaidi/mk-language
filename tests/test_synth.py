"""Deterministic fuzz of the guard & redactor via the synthesizer (cheat #7).

The synthesizer mutates the security-critical behaviours over fixed corpora; here
we run every generated variant through the REAL components and assert each is
caught. No model, no randomness — redaction and the bash guard are deterministic
ground truth (thesis #1), so this is reproducible and CI-safe. It expands security
coverage far past the hand-written golden tasks for free.
"""

from __future__ import annotations

from pathlib import Path

from evals.execute import run_task
from evals.synth import synthesize, synthesize_redact, synthesize_redteam

_ROOT = Path(__file__).resolve().parent.parent


def test_synthesize_is_deterministic_and_uniquely_identified() -> None:
    first = [t.id for t in synthesize()]
    second = [t.id for t in synthesize()]
    assert first == second  # reproducible (no randomness)
    assert len(first) == len(set(first))  # unique task ids


def test_synthesizer_covers_both_security_kinds() -> None:
    assert len(synthesize_redact()) >= 4  # one per redactor pattern family
    assert len(synthesize_redteam()) >= 5  # the catastrophic command classes


def test_redactor_scrubs_every_synthesized_secret() -> None:
    for task in synthesize_redact():
        res = run_task(task, root=_ROOT)
        assert not res.skipped and res.passed, (
            f"{task.id} leaked: {res.assertion_results}"
        )


def test_guard_refuses_every_synthesized_destructive_command() -> None:
    for task in synthesize_redteam():
        res = run_task(task, root=_ROOT)
        assert not res.skipped and res.passed, (
            f"{task.id} not refused: {res.assertion_results}"
        )
