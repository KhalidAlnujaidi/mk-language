"""Resource monitor for the broker (M1 broker depth, vision §5.3).

Samples live VRAM/CPU/RAM into a ``ResourceSnapshot`` whose fields are ``None``
when a measurement could not be taken — *unknown*, never a fabricated ``0``
(honest observability). The three probes are injected so the unit tests run
offline; the real defaults reuse ``nvidia-smi`` (present) and ``psutil`` (Rule
Zero — no hand-parsing of /proc), each degrading to ``None`` on any error.
"""

from __future__ import annotations

import subprocess
from collections.abc import Callable
from dataclasses import dataclass

# Injected probe signatures.
VramProbe = Callable[[], tuple[float | None, float | None]]  # (total_gb, used_gb)
CpuProbe = Callable[[], float | None]  # percent 0..100
RamProbe = Callable[[], tuple[float | None, float | None]]  # (used_gb, total_gb)


@dataclass(frozen=True)
class ResourceSnapshot:
    """A point-in-time resource reading. Every field is ``None`` when unknown."""

    vram_total_gb: float | None
    vram_used_gb: float | None
    cpu_percent: float | None
    ram_used_gb: float | None
    ram_total_gb: float | None

    @property
    def vram_free_gb(self) -> float | None:
        """Free VRAM, or ``None`` when either total or used is unknown."""
        if self.vram_total_gb is None or self.vram_used_gb is None:
            return None
        return self.vram_total_gb - self.vram_used_gb


def _safe_pair(probe: VramProbe | RamProbe) -> tuple[float | None, float | None]:
    try:
        return probe()
    except Exception:  # noqa: BLE001 - best-effort; unknown on any failure
        return (None, None)


def _safe_scalar(probe: CpuProbe) -> float | None:
    try:
        return probe()
    except Exception:  # noqa: BLE001
        return None


# --- Real default probes (best-effort; None on any failure) ------------------


def _nvidia_smi_vram() -> tuple[float | None, float | None]:
    """(total_gb, used_gb) from nvidia-smi, summed across GPUs; None if absent."""
    out = subprocess.run(
        ["nvidia-smi", "--query-gpu=memory.total,memory.used",
         "--format=csv,noheader,nounits"],
        capture_output=True, text=True, timeout=5,
    )
    if out.returncode != 0 or not out.stdout.strip():
        return (None, None)
    total_mb = used_mb = 0.0
    for line in out.stdout.strip().splitlines():
        t, u = (p.strip() for p in line.split(","))
        total_mb += float(t)
        used_mb += float(u)
    return (total_mb / 1024.0, used_mb / 1024.0)


def _psutil_cpu() -> float | None:
    import psutil

    return float(psutil.cpu_percent(interval=0.1))


def _psutil_ram() -> tuple[float | None, float | None]:
    import psutil

    vm = psutil.virtual_memory()
    gb = 1024.0**3
    return (float(vm.used) / gb, float(vm.total) / gb)


def sample(
    *,
    vram_probe: VramProbe = _nvidia_smi_vram,
    cpu_probe: CpuProbe = _psutil_cpu,
    ram_probe: RamProbe = _psutil_ram,
) -> ResourceSnapshot:
    """Sample all three resource probes into a snapshot, nulls on any failure."""
    vram_total, vram_used = _safe_pair(vram_probe)
    cpu = _safe_scalar(cpu_probe)
    ram_used, ram_total = _safe_pair(ram_probe)
    return ResourceSnapshot(
        vram_total_gb=vram_total,
        vram_used_gb=vram_used,
        cpu_percent=cpu,
        ram_used_gb=ram_used,
        ram_total_gb=ram_total,
    )
