"""Resource guardian (self-healing, vision §6 reactive).

Pure decision over a ResourceSnapshot + the loaded model set: when free VRAM
drops below the floor, unload the least-recently-used model, or spill to CPU if
there is nothing to unload. Unknown VRAM → no action (cannot confirm risk).
"""

from __future__ import annotations

from daemon.guardian import guard
from daemon.resources import ResourceSnapshot


def _snap(free_used: tuple[float | None, float | None]) -> ResourceSnapshot:
    total, used = free_used
    return ResourceSnapshot(
        vram_total_gb=total, vram_used_gb=used, cpu_percent=None,
        ram_used_gb=None, ram_total_gb=None,
    )


def test_ok_when_enough_free():
    snap = _snap((24.0, 4.0))  # 20 free
    action = guard(snap, loaded=[("a", 1.0)], min_free_gb=2.0)
    assert action.action == "ok"


def test_unloads_lru_under_pressure():
    snap = _snap((24.0, 23.5))  # 0.5 free
    action = guard(snap, loaded=[("old", 1.0), ("new", 9.0)], min_free_gb=4.0)
    assert action.action == "unload_lru"
    assert action.target == "old"  # smallest last-used timestamp


def test_spills_to_cpu_when_nothing_to_unload():
    snap = _snap((24.0, 23.5))
    action = guard(snap, loaded=[], min_free_gb=4.0)
    assert action.action == "spill_cpu"
    assert action.target is None


def test_no_action_when_vram_unknown():
    snap = _snap((None, None))  # free is None
    action = guard(snap, loaded=[("a", 1.0)], min_free_gb=4.0)
    assert action.action == "ok"
