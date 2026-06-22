"""Config-driven groom stage ordering (vision §9 #3).

A declarative ``config.toml`` decides which groom stages run and in what order,
so the pipeline is reorderable without code changes:

    [[stage]]
    name = "redact"
    enabled = true

Parsed with stdlib ``tomllib`` (Rule Zero — no dependency). The loader is
fail-soft on a *missing or malformed* config (returns the default order), but
strict on a *well-formed but invalid* one: an unknown stage name is rejected so
typos can't silently drop a guard like redact.
"""

from __future__ import annotations

import tomllib
from typing import cast

#: The known groom stages, in their canonical default order.
DEFAULT_ORDER: list[str] = ["redact", "expand", "context", "tag"]
_KNOWN: frozenset[str] = frozenset(DEFAULT_ORDER)


def load_stage_order(toml_text: str | None) -> list[str]:
    """Return the ordered list of enabled groom stage names.

    - ``None`` / empty / malformed TOML → ``DEFAULT_ORDER`` (fail-soft).
    - Well-formed TOML with no ``[[stage]]`` table → ``DEFAULT_ORDER``.
    - Well-formed ``[[stage]]`` entries → the enabled ones, in file order.
    - An unknown stage name → ``ValueError`` (reject; never silently drop).
    """
    if not toml_text:
        return list(DEFAULT_ORDER)
    try:
        data: dict[str, object] = tomllib.loads(toml_text)
    except tomllib.TOMLDecodeError:
        return list(DEFAULT_ORDER)

    stages = data.get("stage")
    if not isinstance(stages, list) or not stages:
        return list(DEFAULT_ORDER)

    order: list[str] = []
    for raw in cast("list[object]", stages):
        entry = cast("dict[str, object]", raw) if isinstance(raw, dict) else {}
        name = entry.get("name")
        if not isinstance(name, str) or name not in _KNOWN:
            raise ValueError(f"unknown groom stage: {name!r}")
        if entry.get("enabled", True):
            order.append(name)
    return order
