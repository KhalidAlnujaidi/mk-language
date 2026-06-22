"""Candidate scoring/ranking for the dispatcher (M1 broker depth, vision §5.3).

Score candidates by capability match (a hard gate), VRAM fit (a hard gate when
both numbers are known), and observed fitness; rank best-first. The ranked list
feeds the fallback chain.
"""

from __future__ import annotations

from daemon.registry import ModelEntry
from daemon.resources import ResourceSnapshot
from daemon.scoring import rank, score

_SNAP = ResourceSnapshot(  # 20 GB free
    vram_total_gb=24.0,
    vram_used_gb=4.0,
    cpu_percent=10.0,
    ram_used_gb=8.0,
    ram_total_gb=64.0,
)


def _m(name: str, **kw: object) -> ModelEntry:
    return ModelEntry(name=name, backend="ollama", **kw)  # type: ignore[arg-type]


def test_missing_required_capability_is_disqualified():
    entry = _m("plain", capabilities=frozenset[str]())
    assert score(entry, _SNAP, required_caps=frozenset({"tools"})) is None


def test_model_that_exceeds_free_vram_is_disqualified():
    entry = _m("huge", vram_gb_required=40.0)  # > 20 GB free
    assert score(entry, _SNAP, required_caps=frozenset()) is None


def test_higher_fitness_ranks_first():
    weak = _m("weak", vram_gb_required=8.0, fitness=0.1)
    strong = _m("strong", vram_gb_required=8.0, fitness=0.9)
    ranked = rank([weak, strong], _SNAP, required_caps=frozenset())
    assert [e.name for e in ranked] == ["strong", "weak"]


def test_unknown_vram_is_not_disqualified():
    entry = _m("mystery", vram_gb_required=None)
    assert score(entry, _SNAP, required_caps=frozenset()) is not None
    ranked = rank([entry], _SNAP, required_caps=frozenset())
    assert [e.name for e in ranked] == ["mystery"]
