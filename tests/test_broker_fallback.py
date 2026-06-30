"""Tests for daemon.fallback — the pure fallback-chain builder (TDD, M1 brick 1).

The chain is derived from the machine manifest (see spec §4.1). It is a pure
function over ``Manifest`` and a ``preferred`` model name, with zero I/O, so it
is exhaustively unit-testable offline.
"""

from __future__ import annotations

from daemon.fallback import build_chain
from kernel.contracts import Tier
from kernel.manifest import CLOUD_DEFAULT_MODEL, LocalModel, Manifest


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


def test_drops_the_deterministic_tier() -> None:
    # available_tiers() always begins with Tier.deterministic(); the broker only
    # executes *model* tiers, so the chain must never contain a deterministic one.
    m = _m(local_models=(LocalModel("small", 4.0),))
    chain = build_chain(m, preferred=None)
    assert all(t.is_model for t in chain)
    assert Tier.deterministic() not in chain


def test_preferred_absent_uses_full_model_list_smallest_first() -> None:
    m = _m(local_models=(LocalModel("big", 18.0), LocalModel("small", 4.0)))
    chain = build_chain(m, preferred=None)
    assert [t.model_name for t in chain] == ["small", "big"]


def test_preferred_pinned_moves_to_front_rest_in_manifest_order() -> None:
    m = _m(
        local_models=(
            LocalModel("a", 4.0),
            LocalModel("b", 8.0),
            LocalModel("c", 12.0),
        )
    )
    chain = build_chain(m, preferred="b")
    # "b" first, then the remaining tiers in manifest (smallest-first) order.
    assert [t.model_name for t in chain] == ["b", "a", "c"]


def test_preferred_unknown_falls_back_to_full_list() -> None:
    m = _m(local_models=(LocalModel("a", 4.0), LocalModel("b", 8.0)))
    chain = build_chain(m, preferred="does-not-exist")
    assert [t.model_name for t in chain] == ["a", "b"]


def test_cloud_appended_last() -> None:
    m = _m(local_models=(LocalModel("a", 4.0),), cloud_available=True)
    chain = build_chain(m, preferred=None)
    assert [t.model_name for t in chain] == ["a", CLOUD_DEFAULT_MODEL]
    assert chain[-1].where == "cloud"


def test_preferred_cloud_pins_cloud_first() -> None:
    m = _m(local_models=(LocalModel("a", 4.0),), cloud_available=True)
    chain = build_chain(m, preferred=CLOUD_DEFAULT_MODEL)
    assert chain[0].where == "cloud"
    assert [t.model_name for t in chain] == [CLOUD_DEFAULT_MODEL, "a"]


def test_empty_manifest_yields_empty_chain() -> None:
    # No fitting local models, no cloud → nothing to execute on.
    assert build_chain(_m(local_models=()), preferred=None) == []


def test_preferred_auto_is_treated_as_no_preference() -> None:
    # The server maps absent/"auto" → no preference; the builder accepts "auto".
    m = _m(local_models=(LocalModel("a", 4.0), LocalModel("b", 8.0)))
    assert build_chain(m, preferred="auto") == build_chain(m, preferred=None)
