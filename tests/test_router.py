"""Tests for kernel.router — Task → Tier routing (TDD, Task 5)."""

from __future__ import annotations

from kernel.contracts import Task, TaskKind, Tier
from kernel.manifest import LocalModel, Manifest
from kernel.router import route


def _m(**kw: object) -> Manifest:
    base: dict[str, object] = dict(
        cpu_count=8,
        ram_gb=60.0,
        gpu_vram_gb=20.0,
        local_models=(),
        cloud_available=False,
    )
    base.update(kw)
    return Manifest(**base)  # type: ignore[arg-type]


def test_ground_truth_routes_to_deterministic() -> None:
    assert route(Task(kind=TaskKind.REDACT), _m()) == Tier.deterministic()


def test_fuzzy_prefers_smallest_fitting_local_model() -> None:
    m = _m(local_models=(LocalModel("big", 18.0), LocalModel("small", 4.0)))
    tier = route(Task(kind=TaskKind.TAG, budget_ms=200), m)
    assert tier is not None
    assert tier.is_model and tier.where == "local" and tier.model_name == "small"


def test_fuzzy_falls_back_to_cloud_when_no_local_fits() -> None:
    m = _m(gpu_vram_gb=None, cloud_available=True)
    tier = route(Task(kind=TaskKind.TAG, budget_ms=200), m)
    assert tier is not None and tier.is_model and tier.where == "cloud"


def test_fuzzy_returns_none_when_nothing_available() -> None:
    m = _m(gpu_vram_gb=None, cloud_available=False)
    assert route(Task(kind=TaskKind.TAG, budget_ms=200), m) is None
