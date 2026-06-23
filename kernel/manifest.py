"""Machine manifest — probe the host and list available execution tiers.

Reads CPU count, RAM, GPU VRAM, and locally-served models from the host
environment, then surfaces those as ``Tier`` values the router can pick from.

All ``_probe_*`` helpers are defensive: they catch every exception and return
``None`` / ``()`` / ``False`` so that ``probe()`` never raises, even on a
machine with no GPU, no ollama, or no network.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import dataclass

from kernel.contracts import Tier

# --- Constants ----------------------------------------------------------------

CLOUD_DEFAULT_MODEL: str = "claude-haiku-4-5"

# --- Data types ---------------------------------------------------------------


@dataclass(frozen=True)
class LocalModel:
    """A model served locally (e.g. via ollama, vLLM, or llama.cpp).

    ``vram_gb_required`` is ``None`` when we have no information about the
    model's memory footprint — we never fabricate a value of ``0``. ``backend``
    names the serving backend so the broker can dispatch to the right transport;
    it defaults to ``"ollama"`` (the only local backend before M2).
    """

    name: str
    vram_gb_required: float | None
    backend: str = "ollama"


@dataclass(frozen=True)
class Manifest:
    """A point-in-time snapshot of the machine's capabilities.

    All numeric fields are ``None`` when the measurement could not be taken.
    ``None`` means *unknown*, never *zero*.
    """

    cpu_count: int | None
    ram_gb: float | None
    gpu_vram_gb: float | None
    local_models: tuple[LocalModel, ...]
    cloud_available: bool

    # --- Derived views --------------------------------------------------------

    def fitting_local_models(self) -> tuple[LocalModel, ...]:
        """Local models whose VRAM requirement is known and fits the GPU.

        A model with ``vram_gb_required is None`` is excluded — we cannot
        verify it fits, so we do not claim it does.  If ``gpu_vram_gb`` is
        ``None`` no local model is claimed to fit.
        """
        if self.gpu_vram_gb is None:
            return ()
        fitting = [
            m
            for m in self.local_models
            if m.vram_gb_required is not None and m.vram_gb_required <= self.gpu_vram_gb
        ]

        def _vram_key(m: LocalModel) -> float:
            # vram_gb_required is guaranteed non-None by the list comprehension above.
            assert m.vram_gb_required is not None
            return m.vram_gb_required

        # Sort by smallest VRAM requirement first.
        fitting.sort(key=_vram_key)
        return tuple(fitting)

    def available_tiers(self) -> tuple[Tier, ...]:
        """Ordered list of execution tiers this machine can offer right now.

        Order:
        1. ``Tier.deterministic()`` — always first (plain code, no model).
        2. One ``Tier.model(m.name, where="local")`` per fitting local model,
           smallest VRAM first.
        3. ``Tier.model(CLOUD_DEFAULT_MODEL, where="cloud")`` iff cloud is
           reachable (an API key is set).
        """
        tiers: list[Tier] = [Tier.deterministic()]
        for m in self.fitting_local_models():
            tiers.append(Tier.model(m.name, where="local", backend=m.backend))
        if self.cloud_available:
            tiers.append(
                Tier.model(CLOUD_DEFAULT_MODEL, where="cloud", backend="anthropic")
            )
        return tuple(tiers)


# --- Individual probes (each returns None / () / False on any failure) --------


def _probe_cpu() -> int | None:
    """Return the logical CPU count, or ``None`` on any failure."""
    try:
        return os.cpu_count()
    except Exception:
        return None


def _probe_ram_gb() -> float | None:
    """Parse ``/proc/meminfo`` ``MemTotal`` kB → GB.  ``None`` if absent/unparseable."""
    try:
        with open("/proc/meminfo", encoding="utf-8") as fh:
            for line in fh:
                if line.startswith("MemTotal:"):
                    kb = float(line.split()[1])
                    return kb / (1024.0 * 1024.0)
        return None
    except Exception:
        return None


def _probe_gpu_vram_gb() -> float | None:
    """Query nvidia-smi for total VRAM in MiB, convert to GB.

    Returns ``None`` on any failure (binary missing, non-zero exit, parse error).
    """
    try:
        if shutil.which("nvidia-smi") is None:
            return None
        result = subprocess.run(
            ["nvidia-smi", "--query-gpu=memory.total", "--format=csv,noheader,nounits"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode != 0:
            return None
        first_line = result.stdout.strip().splitlines()[0].strip()
        mib = float(first_line)
        return mib / 1024.0
    except Exception:
        return None


def _probe_local_models() -> tuple[LocalModel, ...]:
    """List models from ``ollama list``.  Empty tuple if ollama is missing or fails."""
    try:
        if shutil.which("ollama") is None:
            return ()
        result = subprocess.run(
            ["ollama", "list"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode != 0:
            return ()
        lines = result.stdout.strip().splitlines()
        # First line is the header (NAME  ID  SIZE  MODIFIED …); skip it.
        models: list[LocalModel] = []
        for line in lines[1:]:
            parts = line.split()
            if not parts:
                continue
            models.append(LocalModel(name=parts[0], vram_gb_required=None))
        return tuple(models)
    except Exception:
        return ()


def _probe_cloud() -> bool:
    """``True`` iff at least one recognised API-key env var is set and non-empty."""
    try:
        for var in ("ANTHROPIC_API_KEY", "CLAUDE_API_KEY"):
            if os.environ.get(var):
                return True
        return False
    except Exception:
        return False


# --- Top-level assembler ------------------------------------------------------


def probe() -> Manifest:
    """Run all probes and assemble a ``Manifest``.

    Never raises.  Each probe degrades gracefully so callers always get a
    complete ``Manifest`` object, even on a bare container with no GPU.
    """
    return Manifest(
        cpu_count=_probe_cpu(),
        ram_gb=_probe_ram_gb(),
        gpu_vram_gb=_probe_gpu_vram_gb(),
        local_models=_probe_local_models(),
        cloud_available=_probe_cloud(),
    )
