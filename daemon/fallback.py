"""The fallback-chain builder (broker brick 1, spec §4.1).

A pure function that turns a machine ``Manifest`` plus an optional preferred
model name into an ordered list of *model* ``Tier`` values for the executor to
walk. Zero I/O — all the host probing already happened in ``manifest.probe()``,
so this is exhaustively unit-testable offline.

Design (spec §4.1):

  - Start from ``manifest.available_tiers()`` (already ordered: deterministic
    first, then local models smallest-VRAM-first, then cloud).
  - Drop ``Tier.deterministic()`` — the broker only executes model tiers.
  - If ``preferred`` names a tier in the list, move it to the front and keep the
    remaining tiers in manifest order; otherwise return the full list as-is.
  - Return ``[]`` when no model tier exists (the caller fails soft — spec §6).
"""

from __future__ import annotations

from kernel.contracts import Tier
from kernel.manifest import Manifest
from daemon.registry import Registry
from daemon.resources import ResourceSnapshot
from daemon.scoring import rank

# The server maps an absent or "auto" model field to "no preference"; accept the
# sentinel here too so the builder stays the single source of that rule.
_NO_PREFERENCE: frozenset[str] = frozenset({"auto"})


def build_chain(
    manifest: Manifest, 
    preferred: str | None,
    registry: Registry | None = None,
    snapshot: ResourceSnapshot | None = None,
) -> list[Tier]:
    """Return the ordered fallback chain of model tiers for *manifest*.

    The chain is the manifest's model tiers (deterministic tier removed),
    smallest local first then cloud. When *preferred* names one of those tiers
    it is pinned to the front and the rest keep their manifest order. An absent,
    ``"auto"``, or unknown *preferred* leaves the manifest order untouched.

    Returns an empty list when the machine offers no model tier at all.
    """
    if registry is not None and snapshot is not None:
        # Use intelligent scoring if registry and snapshot are provided
        entries = []
        for tier in manifest.available_tiers():
            if tier.is_model and tier.where == "local":
                entry = registry.get(tier.model_name or "")
                if entry is not None and not entry.quarantined:
                    entries.append(entry)
        
        ranked_entries = rank(entries, snapshot, required_caps=frozenset())
        
        # Build model tiers preserving the deterministic / cloud order from available_tiers
        model_tiers = []
        
        # First add the locally ranked models
        for entry in ranked_entries:
            model_tiers.append(Tier.model(entry.name, where="local", backend=entry.backend))
            
        # Then append any cloud models from the manifest
        for tier in manifest.available_tiers():
            if tier.is_model and tier.where == "cloud":
                model_tiers.append(tier)
    else:
        # Static fallback: smallest first
        model_tiers = [t for t in manifest.available_tiers() if t.is_model]

    if preferred is None or preferred in _NO_PREFERENCE:
        return model_tiers

    pinned = next((t for t in model_tiers if t.model_name == preferred), None)
    if pinned is None:
        # Unknown preferred → fall back to the full list rather than failing.
        return model_tiers

    rest = [t for t in model_tiers if t is not pinned]
    return [pinned, *rest]
