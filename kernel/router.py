"""Task → Tier routing (vision §4, thesis #1).

Ground-truth tasks run as plain code (``Tier.deterministic()``).
Fuzzy tasks get the smallest fitting local model, then cloud, then ``None``.
"""

from __future__ import annotations

from kernel.contracts import Determinism, Task, Tier
from kernel.manifest import Manifest


def route(task: Task, manifest: Manifest) -> Tier | None:
    """Return the cheapest capable ``Tier`` for *task*, or ``None`` if none exists.

    - ``GROUND_TRUTH`` → ``Tier.deterministic()`` (no model; thesis #1).
    - ``FUZZY`` → first local-model tier from ``manifest.available_tiers()``
      (manifest already orders local models smallest-VRAM-first); else the
      cloud tier if present; else ``None`` (caller must fail soft).
    """
    if task.determinism is Determinism.GROUND_TRUTH:
        return Tier.deterministic()

    # FUZZY: iterate the manifest's ordered tier list; prefer local, accept cloud.
    cloud_tier: Tier | None = None
    for tier in manifest.available_tiers():
        if not tier.is_model:
            continue  # skip Tier.deterministic()
        if tier.where == "local":
            return tier  # smallest fitting local model — done
        if tier.where == "cloud":
            cloud_tier = tier  # remember cloud in case no local fits

    return cloud_tier  # None when cloud is also absent
