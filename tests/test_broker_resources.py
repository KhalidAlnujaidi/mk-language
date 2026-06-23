"""Resource monitor (M1 broker depth, vision §5.3).

Live VRAM/CPU/RAM with honest nulls. Probes are injected so the unit tests run
offline; the real defaults reuse nvidia-smi + psutil (Rule Zero).
"""

from __future__ import annotations

from daemon.resources import ResourceSnapshot, sample


def test_sample_collects_all_injected_probes():
    snap = sample(
        vram_probe=lambda: (24.0, 9.0),
        cpu_probe=lambda: 12.5,
        ram_probe=lambda: (10.0, 60.0),
    )
    assert snap.vram_total_gb == 24.0
    assert snap.vram_used_gb == 9.0
    assert snap.vram_free_gb == 15.0
    assert snap.cpu_percent == 12.5
    assert snap.ram_used_gb == 10.0
    assert snap.ram_total_gb == 60.0


def test_failed_probe_is_null_never_zero():
    def boom() -> tuple[float | None, float | None]:
        raise RuntimeError("no gpu here")

    snap = sample(vram_probe=boom, cpu_probe=lambda: None, ram_probe=boom)
    assert snap.vram_total_gb is None  # unknown, not a fabricated 0.0
    assert snap.vram_used_gb is None
    assert snap.vram_free_gb is None
    assert snap.cpu_percent is None
    assert snap.ram_used_gb is None
    assert snap.ram_total_gb is None


def test_vram_free_is_null_when_either_input_missing():
    snap = sample(
        vram_probe=lambda: (24.0, None),
        cpu_probe=lambda: None,
        ram_probe=lambda: (None, None),
    )
    assert isinstance(snap, ResourceSnapshot)
    assert snap.vram_free_gb is None
