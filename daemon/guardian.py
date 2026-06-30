"""Resource guardian (self-healing, vision §6 reactive).

A pure decision over the live ResourceSnapshot (from daemon.resources) and the
set of currently-loaded models. Under VRAM pressure it picks the
least-recently-used model to unload, or spills to CPU when there is nothing left
to unload. Unknown free VRAM yields no action — we never act on a risk we cannot
confirm (honest observability).
"""

from __future__ import annotations

from dataclasses import dataclass

from daemon.resources import ResourceSnapshot

#: A loaded model as (name, last_used_timestamp). Lower timestamp = older use.
LoadedModel = tuple[str, float]


@dataclass(frozen=True)
class GuardAction:
    """What the guardian recommends: ``ok`` | ``unload_lru`` | ``spill_cpu``."""

    action: str
    target: str | None = None


def guard(
    snapshot: ResourceSnapshot,
    loaded: list[LoadedModel],
    *,
    min_free_gb: float,
) -> GuardAction:
    """Recommend an action to keep free VRAM at or above *min_free_gb*."""
    free = snapshot.vram_free_gb
    if free is None or free >= min_free_gb:
        return GuardAction("ok")  # fine, or cannot confirm risk → do nothing
    if not loaded:
        return GuardAction("spill_cpu")
    lru_name = min(loaded, key=lambda m: m[1])[0]
    return GuardAction("unload_lru", target=lru_name)
