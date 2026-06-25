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
