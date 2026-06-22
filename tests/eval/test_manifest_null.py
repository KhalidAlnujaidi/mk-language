# swarm-drafted (node=gemma-agent-3, model=Nemotron-14B); curated locally
# Behavioral: probe() is honest (numeric fields None when unknown, never a
# fabricated 0/False) and available_tiers() is ordered deterministic -> local
# -> cloud, with local models smallest-VRAM-first. (Fixed: the draft asserted
# tier.vram_required, which lives on LocalModel/Manifest, not Tier, plus a
# `raiseAssertionError` token glitch.)
from kernel.manifest import Manifest, probe


def test_probe_is_honest_about_unknowns():
    mf = probe()
    assert isinstance(mf, Manifest)
    # None means unknown; a real measurement is positive. Never a fabricated 0.
    for field in (mf.cpu_count, mf.ram_gb, mf.gpu_vram_gb):
        assert field is None or field > 0


def test_tiers_ordered_deterministic_local_cloud():
    tiers = probe().available_tiers()
    assert isinstance(tiers, tuple)
    assert tiers[0].is_model is False  # deterministic always first

    wheres = [t.where for t in tiers if t.is_model]
    # every local tier precedes every cloud tier
    last_local = max((i for i, w in enumerate(wheres) if w == "local"), default=-1)
    first_cloud = next((i for i, w in enumerate(wheres) if w == "cloud"), len(wheres))
    assert last_local < first_cloud


def test_fitting_local_models_sorted_by_vram():
    # fitting_local_models() only returns models with a known (non-None) VRAM.
    vrams = [
        m.vram_gb_required
        for m in probe().fitting_local_models()
        if m.vram_gb_required is not None
    ]
    assert vrams == sorted(vrams)  # ascending
