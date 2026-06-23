"""Tiny defensive coercion helpers for untyped JSON (stdlib-only, kernel-pure).

Decoded JSON is ``object`` at the type level, so narrowing it to the shapes we
expect (a mapping, an int) needs a guarded cast in one place rather than scattered
``isinstance`` checks. Both the manifest's backend probes and the broker's
transport parse untyped JSON, so these live in the kernel and are imported
outward (daemon → kernel is the allowed direction).
"""

from __future__ import annotations


def as_dict(value: object) -> dict[str, object]:
    """Return *value* as a ``dict[str, object]`` if it is a mapping, else ``{}``."""
    if isinstance(value, dict):
        return {str(k): v for k, v in value.items()}  # type: ignore[misc]
    return {}


def as_int(value: object) -> int | None:
    """Return *value* as an ``int`` if it is one (and not a bool), else ``None``."""
    return value if isinstance(value, int) and not isinstance(value, bool) else None
