"""Model registry with canary verification (M1 broker depth, vision §4.1).

Per-model metadata plus a registration-time **canary**: a model declares its
capabilities, the broker runs a tiny canary task to verify it actually responds,
and a model that fails (or whose canary raises) is **quarantined** — recorded
but excluded from routing candidates. "Liars get quarantined" (§4.1).

The canary is injected (``Callable[[ModelEntry], bool]``) so the registry is
unit-testable offline; the real canary issues a one-token completion through the
backend transport.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field, replace

#: Verify a model responds. Returns True to admit, False/raise to quarantine.
Canary = Callable[["ModelEntry"], bool]


@dataclass(frozen=True)
class ModelEntry:
    """Registry metadata for one model.

    ``vram_gb_required`` and ``fitness`` are ``None`` when unknown (never a
    fabricated value). ``quarantined`` is set by registration, not by callers.
    """

    name: str
    backend: str
    vram_gb_required: float | None = None
    capabilities: frozenset[str] = field(default_factory=lambda: frozenset[str]())
    preferred_for: frozenset[str] = field(default_factory=lambda: frozenset[str]())
    fitness: float | None = None
    quarantined: bool = False


class Registry:
    """An in-memory model registry keyed by model name."""

    def __init__(self) -> None:
        self._entries: dict[str, ModelEntry] = {}

    def register(self, entry: ModelEntry, canary: Canary) -> ModelEntry:
        """Verify *entry* with *canary*; store it, quarantined iff it fails."""
        try:
            passed = bool(canary(entry))
        except Exception:  # noqa: BLE001 - any canary failure quarantines the model
            passed = False
        stored = replace(entry, quarantined=not passed)
        self._entries[entry.name] = stored
        return stored

    def get(self, name: str) -> ModelEntry | None:
        """The entry for *name* (quarantined or not), or ``None`` if unknown."""
        return self._entries.get(name)

    def candidates(self) -> tuple[ModelEntry, ...]:
        """All non-quarantined entries — the models routing may consider."""
        return tuple(e for e in self._entries.values() if not e.quarantined)

    def all(self) -> tuple[ModelEntry, ...]:
        """Every registered entry, including quarantined ones."""
        return tuple(self._entries.values())
