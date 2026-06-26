"""Machine manifest — probe the host and list available execution tiers.

Reads CPU count, RAM, GPU VRAM, and locally-served models from the host
environment, then surfaces those as ``Tier`` values the router can pick from.

All ``_probe_*`` helpers are defensive: they catch every exception and return
``None`` / ``()`` / ``False`` so that ``probe()`` never raises, even on a
machine with no GPU, no ollama, or no network.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import urllib.request
from dataclasses import dataclass

from kernel.contracts import Tier
from kernel.jsonutil import as_dict

# --- Constants ----------------------------------------------------------------

CLOUD_DEFAULT_MODEL: str = "claude-haiku-4-5"

# Canonical OpenAI-compatible endpoint per local backend (env var, default URL).
# The SINGLE SOURCE OF TRUTH for where local backends live: the manifest probes
# these, and ``daemon.backends`` imports :func:`local_backend_urls` to dispatch
# to the same URLs. Kept in the (stdlib-only) kernel so both layers agree.
_LOCAL_BACKEND_DEFAULTS: dict[str, tuple[str, str]] = {
    "ollama": ("KINOX_OLLAMA_URL", "http://127.0.0.1:11434/v1"),
    "vllm": ("KINOX_VLLM_URL", "http://127.0.0.1:8000/v1"),
    "llamacpp": ("KINOX_LLAMACPP_URL", "http://127.0.0.1:8080/v1"),
}

# How long an OpenAI ``/v1/models`` probe waits before giving up (seconds).
_PROBE_TIMEOUT_S = 2.0


def local_backend_urls() -> dict[str, str]:
    """The configured base URL per local backend, env read at call time.

    Lazy (not import-time) so operators/tests can override endpoints via env.
    """
    return {
        name: os.environ.get(env_var, default)
        for name, (env_var, default) in _LOCAL_BACKEND_DEFAULTS.items()
    }

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


def _http_get_json(url: str, *, timeout: float = _PROBE_TIMEOUT_S) -> object | None:
    """GET *url* and JSON-decode the body; ``None`` on any failure (stdlib only).

    Defensive like every other probe: unreachable host, timeout, non-200, or
    unparseable body all collapse to ``None`` so ``probe()`` never raises. This is
    the seam tests stub (``monkeypatch`` the module attribute) to avoid a live
    server.
    """
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:  # noqa: S310
            if getattr(resp, "status", 200) != 200:
                return None
            return json.loads(resp.read().decode("utf-8"))
    except Exception:
        return None


def _probe_openai_models(
    base_url: str, backend: str, *, timeout: float = _PROBE_TIMEOUT_S
) -> tuple[LocalModel, ...]:
    """List models from an OpenAI-compatible ``{base_url}/models`` endpoint.

    Each returned model id becomes a ``LocalModel`` tagged with *backend* and an
    unknown (``None``) VRAM footprint. Any failure or unexpected shape yields an
    empty tuple — vLLM/llama.cpp simply contribute nothing when not running.
    """
    data = _http_get_json(base_url.rstrip("/") + "/models", timeout=timeout)
    items = as_dict(data).get("data")
    if not isinstance(items, list):
        return ()
    item_list: list[object] = list(items)  # type: ignore[arg-type]  # untyped JSON
    models: list[LocalModel] = []
    for item in item_list:
        model_id = as_dict(item).get("id")
        if isinstance(model_id, str) and model_id:
            models.append(
                LocalModel(name=model_id, vram_gb_required=None, backend=backend)
            )
    return tuple(models)


def _probe_cloud() -> bool:
    """``True`` iff at least one recognised API-key env var is set and non-empty."""
    try:
        for var in (
            "ANTHROPIC_API_KEY",
            "CLAUDE_API_KEY",
            "ZAI_API_KEY",
            "OPENROUTER_API_KEY",
        ):
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

    Local models come from all configured backends: Ollama (via its CLI) plus any
    vLLM / llama.cpp servers reachable on their OpenAI-compatible endpoints. A
    backend that is not running simply contributes no models.
    """
    urls = local_backend_urls()
    local_models = (
        *_probe_local_models(),
        *_probe_openai_models(urls["vllm"], "vllm"),
        *_probe_openai_models(urls["llamacpp"], "llamacpp"),
    )
    return Manifest(
        cpu_count=_probe_cpu(),
        ram_gb=_probe_ram_gb(),
        gpu_vram_gb=_probe_gpu_vram_gb(),
        local_models=local_models,
        cloud_available=_probe_cloud(),
    )
