"""Candidate scoring + ranking for the dispatcher (M1 broker depth, vision §5.3).

Pure functions over a ``ModelEntry`` and a ``ResourceSnapshot``:

  - ``score`` returns a float, or ``None`` when the model is *disqualified* by a
    hard gate — it lacks a required capability, or its known VRAM need exceeds
    the known free VRAM. Unknown VRAM is NOT a disqualifier (we cannot prove it
    won't fit; the fallback chain handles a real OOM).
  - ``rank`` scores every entry and returns the qualified ones best-first.

Higher observed fitness and more post-load VRAM headroom score higher.
"""

from __future__ import annotations

from daemon.registry import ModelEntry
from daemon.resources import ResourceSnapshot


def score(
    entry: ModelEntry,
    snapshot: ResourceSnapshot,
    required_caps: frozenset[str],
) -> float | None:
    """A routing score for *entry*, or ``None`` if a hard gate disqualifies it."""
    # Capability gate: the model must declare every required capability.
    if not required_caps <= entry.capabilities:
        return None

    free = snapshot.vram_free_gb
    need = entry.vram_gb_required

    # VRAM gate: only when both numbers are known. Unknown → not disqualified.
    if need is not None and free is not None and need > free:
        return None

    result = 1.0
    if entry.fitness is not None:
        result += entry.fitness
    # Reward leftover headroom after the model loads (smaller model on a big GPU).
    if need is not None and free is not None and free > 0:
        result += (free - need) / free
    return result


def rank(
    entries: list[ModelEntry],
    snapshot: ResourceSnapshot,
    required_caps: frozenset[str],
) -> list[ModelEntry]:
    """Return the qualified entries ordered best score first."""
    scored = ((e, score(e, snapshot, required_caps)) for e in entries)
    qualified = [(e, s) for e, s in scored if s is not None]
    qualified.sort(key=lambda es: es[1], reverse=True)
    return [e for e, _ in qualified]
