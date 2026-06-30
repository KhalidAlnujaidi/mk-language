"""Tests for the load-bearing kernel contracts (vision §4).

These types are the kernel's spine: Task, Tier, Annotation, EventRecord,
FailDirection, Determinism. Two of them — EventRecord.correction_of (thesis #3)
and FailDirection (thesis #2) — must exist from commit one.
"""

from __future__ import annotations

import dataclasses

import pytest
from kernel.contracts import (
    Annotation,
    Determinism,
    EventRecord,
    FailDirection,
    Task,
    TaskKind,
    Tier,
)

# --- Determinism / FailDirection: the two axis enums --------------------------


def test_determinism_is_binary() -> None:
    assert {d.name for d in Determinism} == {"GROUND_TRUTH", "FUZZY"}


def test_fail_direction_has_closed_and_soft() -> None:
    # thesis #2 — fail-direction is per-component, never a global default.
    assert {f.name for f in FailDirection} == {"CLOSED", "SOFT"}


# --- TaskKind carries an inherent determinism --------------------------------


def test_task_kind_maps_to_determinism() -> None:
    # A kind's determinism is intrinsic: redaction is ground-truth, tagging fuzzy.
    assert TaskKind.REDACT.determinism is Determinism.GROUND_TRUTH
    assert TaskKind.TAG.determinism is Determinism.FUZZY


# --- Task: fuzzy needs a budget, ground-truth forbids one --------------------


def test_fuzzy_task_requires_a_budget() -> None:
    with pytest.raises(ValueError):
        Task(kind=TaskKind.TAG)  # fuzzy → must declare budget_ms


def test_ground_truth_task_forbids_a_budget() -> None:
    with pytest.raises(ValueError):
        Task(kind=TaskKind.REDACT, budget_ms=50)  # no model → no budget


def test_task_exposes_its_kinds_determinism() -> None:
    t = Task(kind=TaskKind.TAG, budget_ms=200)
    assert t.determinism is Determinism.FUZZY
    assert t.budget_ms == 200


def test_task_is_frozen() -> None:
    t = Task(kind=TaskKind.REDACT)
    with pytest.raises(dataclasses.FrozenInstanceError):
        t.kind = TaskKind.TAG  # type: ignore[misc]


# --- Tier: the router's output, with structural invariants -------------------


def test_deterministic_tier_has_no_model() -> None:
    tier = Tier.deterministic()
    assert tier.is_model is False
    assert tier.model_name is None
    assert tier.where is None


def test_model_tier_names_a_model_and_location() -> None:
    tier = Tier.model("qwen2.5-coder:7b", where="local")
    assert tier.is_model is True
    assert tier.model_name == "qwen2.5-coder:7b"
    assert tier.where == "local"


def test_model_tier_rejects_unknown_location() -> None:
    with pytest.raises(ValueError):
        Tier.model("gpt-x", where="mars")  # type: ignore[arg-type]


def test_model_tier_defaults_to_ollama_backend() -> None:
    # Backward compatible: an untagged local tier is Ollama (today's only backend).
    tier = Tier.model("qwen2.5-coder:7b", where="local")
    assert tier.backend == "ollama"


def test_model_tier_carries_an_explicit_backend() -> None:
    # M2: a tier knows which backend serves it so the transport can be chosen.
    tier = Tier.model("qwen2.5-coder:7b", where="local", backend="vllm")
    assert tier.backend == "vllm"
    assert tier.where == "local"
    assert tier.model_name == "qwen2.5-coder:7b"


def test_deterministic_tier_has_no_backend() -> None:
    # Plain code runs nowhere — no backend to name.
    assert Tier.deterministic().backend is None


# --- Annotation: passthrough vs the single halt path -------------------------


def test_passthrough_annotation_is_not_blocked() -> None:
    ann = Annotation.passthrough(["context line"])
    assert ann.is_blocked is False
    assert ann.lines == ["context line"]
    assert ann.block is None


def test_halt_annotation_carries_a_reason_and_is_blocked() -> None:
    # block is the ONLY way to halt (vision §4 primitive 3).
    ann = Annotation.halt("contains an unredactable secret")
    assert ann.is_blocked is True
    assert ann.block == "contains an unredactable secret"


# --- EventRecord: correction_of must exist from commit one -------------------


def test_event_record_correction_slot_defaults_to_none() -> None:
    ev = EventRecord(task_id="t1", kind="tag", tier="model:local")
    assert ev.correction_of is None


def test_event_record_can_be_marked_as_a_correction() -> None:
    # thesis #3 — the next-turn correction is captured structurally.
    original = EventRecord(task_id="t2", kind="tag", tier="model:local")
    corrected = original.as_correction_of("t1")
    assert corrected.correction_of == "t1"
    # original fields preserved, immutably
    assert corrected.task_id == "t2"
