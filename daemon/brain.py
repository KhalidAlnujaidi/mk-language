"""The brain tier — which model does kinox's high-value reasoning.

kinox's brain is **cloud by default, local as the fallback** — always. A frontier
model (``glm-5.2`` on the z.ai cloud backend, out of the box) does the high-value
reasoning (vision §3 thesis #1: the expensive model is called for exactly the
hard part); the local model is the fail-soft fallback so a cloud outage or a
missing key degrades to local rather than taking the workspace offline (the
broker fails SOFT, spec §6). Cheap groundwork (grooming, tagging, deterministic
checks) stays local regardless — only the *reasoning* tier is the brain.

Overrides (env):
- ``KINOX_BRAIN`` — the brain model name. Defaults to :data:`DEFAULT_BRAIN_MODEL`.
  Set it to ``local`` / ``off`` / ``none`` (or empty) to disable the cloud brain
  and use only the local fallback — the hermetic-test and offline path.
- ``KINOX_BRAIN_BACKEND`` / ``KINOX_BRAIN_WHERE`` — where the brain is served
  (default the cloud ``zai`` backend). The bearer key lives in the backend's own
  env var (``ZAI_API_KEY`` for ``zai``), never here and never in a tracked file.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from kernel.contracts import Location, Tier

#: kinox's default brain: GLM-5.2 on z.ai, which speaks the OpenAI protocol and so
#: reuses the generic transport (Rule Zero) — only the bearer key and
#: ``exact=False`` differ (see ``daemon.backends``).
DEFAULT_BRAIN_MODEL = "glm-5.2"
DEFAULT_BRAIN_BACKEND = "zai"
DEFAULT_BRAIN_WHERE: Location = "cloud"

#: ``KINOX_BRAIN`` values (case-insensitive) that mean "no cloud brain — local only".
_DISABLE = frozenset({"", "local", "off", "none"})


def brain_tier(fallback: Tier | None = None) -> Tier | None:
    """kinox's reasoning brain — cloud (``glm-5.2``) by default.

    Returns the cloud brain tier unless ``KINOX_BRAIN`` is set to a disabling
    value (``local`` / ``off`` / ``none`` / empty), in which case it returns
    *fallback* (the local tier). The brand/where/backend come from the
    ``KINOX_BRAIN*`` env, defaulting to ``glm-5.2`` on the cloud ``zai`` backend."""
    name = os.environ.get("KINOX_BRAIN", DEFAULT_BRAIN_MODEL)
    if name.strip().lower() in _DISABLE:
        return fallback
    backend = os.environ.get("KINOX_BRAIN_BACKEND", DEFAULT_BRAIN_BACKEND)
    where_env = os.environ.get("KINOX_BRAIN_WHERE", DEFAULT_BRAIN_WHERE)
    # Narrow the env string to the ``Location`` literal; an unrecognised value
    # falls back to the default rather than reaching Tier.model's ValueError.
    where: Location = (
        where_env if where_env in ("local", "cloud") else DEFAULT_BRAIN_WHERE
    )
    return Tier.model(name, where=where, backend=backend)


def brain_chain(fallback: Tier | None) -> list[Tier]:
    """The reasoning fallback chain: the cloud brain first, then *fallback* (local).

    - Default: ``[cloud_brain, local]`` — cloud reasons, local catches a cloud
      outage (fail SOFT, spec §6).
    - Cloud disabled (``KINOX_BRAIN=local``): ``[local]``.
    - No local model: ``[cloud_brain]`` — the cloud brain answers on its own.
    - Neither available: ``[]`` (the caller surfaces a no-model message).

    Never lists the same tier twice (the executor would otherwise retry an
    identical tier on failure)."""
    brain = brain_tier()
    chain: list[Tier] = []
    if brain is not None:
        chain.append(brain)
    if fallback is not None and fallback != brain:
        chain.append(fallback)
    return chain


# --- selection: presets, description, and live + persisted switching ----------

#: Where ``kx`` reads secrets/config and where :func:`set_brain` persists choices.
ENV_FILE = Path.home() / ".kinox" / "env"


@dataclass(frozen=True)
class BrainChoice:
    """One selectable brain. ``model is None`` means "local only" (the cloud brain
    is disabled and the local fallback answers)."""

    label: str
    model: str | None
    backend: str | None = None
    where: str | None = None


#: The built-in brain menu shown by ``/model``. OpenRouter is open-ended (any
#: model id), so it is offered as a freeform choice in the TUI rather than listed
#: here. These cover the local fallback and the z.ai GLM Coding Plan models.
BRAIN_PRESETS: tuple[BrainChoice, ...] = (
    BrainChoice("local (no cloud — the fallback model)", None),
    BrainChoice("z.ai · glm-5.2  (coding plan)", "glm-5.2", "zai", "cloud"),
    BrainChoice("z.ai · glm-4.7  (coding plan)", "glm-4.7", "zai", "cloud"),
    BrainChoice("z.ai · glm-5-turbo  (coding plan)", "glm-5-turbo", "zai", "cloud"),
)


def describe_brain() -> str:
    """A short human label for the currently-configured brain.

    ``"local"`` when the cloud brain is disabled, else
    ``"<model> (<backend> · <where>)"``."""
    tier = brain_tier()
    if tier is None:
        return "local"
    return f"{tier.model_name} ({tier.backend} · {tier.where})"


def set_brain(
    model: str | None,
    backend: str | None = None,
    where: str | None = None,
    *,
    env_file: Path | None = None,
) -> str:
    """Switch the active brain — apply to the live environment AND persist it.

    ``model is None`` selects local-only (``KINOX_BRAIN=local``). Otherwise the
    cloud brain is ``model`` on *backend* (default ``zai``) at *where* (default
    ``cloud``). Writes ``KINOX_BRAIN*`` to the process env so the *next chat turn*
    uses it immediately (``brain_chain`` re-reads env each turn), and upserts the
    same keys into ``~/.kinox/env`` so the choice survives a restart. Returns the
    new :func:`describe_brain` label."""
    name = model if model else "local"
    be = backend or DEFAULT_BRAIN_BACKEND
    wh = where or DEFAULT_BRAIN_WHERE
    updates = {
        "KINOX_BRAIN": name,
        "KINOX_BRAIN_BACKEND": be,
        "KINOX_BRAIN_WHERE": wh,
    }
    os.environ.update(updates)
    _upsert_env(env_file or ENV_FILE, updates)
    return describe_brain()


def _upsert_env(path: Path, updates: dict[str, str]) -> None:
    """Set each ``KEY=value`` in *path*, replacing existing keys and preserving
    every other line (comments, blanks, unrelated secrets). Creates the file."""
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        lines = []
    out: list[str] = []
    seen: set[str] = set()
    for line in lines:
        stripped = line.strip()
        if stripped and not stripped.startswith("#") and "=" in stripped:
            key = stripped.split("=", 1)[0].strip()
            if key in updates:
                out.append(f"{key}={updates[key]}")
                seen.add(key)
                continue
        out.append(line)
    for key, value in updates.items():
        if key not in seen:
            out.append(f"{key}={value}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(out) + "\n", encoding="utf-8")


def openrouter_text_models(*, limit: int = 40) -> list[str]:
    """Live list of OpenRouter model ids that are text→text, best-effort.

    Fetches ``/models`` (public, no key needed) and keeps models whose
    architecture takes text in and text out. Returns ``[]`` on any failure (no
    network, bad shape) — the caller treats that as "type an id yourself"."""
    import json
    import urllib.request

    from kernel.jsonutil import as_dict

    from daemon.backends import cloud_backend_specs

    spec = cloud_backend_specs().get("openrouter")
    if spec is None:
        return []
    url = spec.base_url.rstrip("/") + "/models"
    try:
        with urllib.request.urlopen(url, timeout=5) as resp:  # noqa: S310
            raw: object = json.loads(resp.read().decode("utf-8"))
    except Exception:
        return []
    items = as_dict(raw).get("data")
    if not isinstance(items, list):
        return []
    item_list: list[object] = list(items)  # type: ignore[arg-type]  # untyped JSON
    ids: list[str] = []
    for item in item_list:
        info = as_dict(item)
        arch = as_dict(info.get("architecture"))
        ins = arch.get("input_modalities")
        outs = arch.get("output_modalities")
        mid = info.get("id")
        text_in = isinstance(ins, list) and "text" in ins
        text_out = isinstance(outs, list) and "text" in outs
        if isinstance(mid, str) and mid and text_in and text_out:
            ids.append(mid)
        if len(ids) >= limit:
            break
    return ids
