"""Layered, profile-aware config for the status line (CodeWhale Tier-2 #4).

CodeWhale's config is declarative TOML with a global file, a per-project overlay,
and an env-selected *profile* (``CODEWHALE_PROFILE``). This realises the same
shape for kinox's status-line chips (the consumer built in
``products/dashboard/statusline.py``) — the "config profiles" half of grab #4,
paired with the chips it configures.

Precedence (highest first) — the first source that yields a valid, non-empty
chip list wins:

  1. project file, ``[profile.<name>.tui] status_chips``
  2. project file, ``[tui] status_chips``
  3. global file,  ``[profile.<name>.tui] status_chips``
  4. global file,  ``[tui] status_chips``
  5. ``statusline.DEFAULT_CHIPS``

So a project tightens/overrides the global, and a selected profile overrides the
base within each file. Parsed with stdlib ``tomllib`` (Rule Zero, no dependency).

Fail-direction (matches ``products/groom/config.py``): fail-SOFT on a *missing or
malformed* file (fall to the next source, ultimately the default), but STRICT on
a *well-formed but invalid* one — an unknown chip name raises ``ValueError`` so a
typo is caught loudly rather than silently dropping a chip.
"""

from __future__ import annotations

import tomllib
from typing import cast

from products.dashboard.statusline import DEFAULT_CHIPS, KNOWN_CHIPS


def _validated_chips(raw: object, source: str) -> list[str] | None:
    """Coerce a ``status_chips`` value to a validated list, or ``None`` if absent.

    A non-list, or an empty list, is treated as "not set here" (``None``) so the
    next source in precedence is consulted. An unknown chip name raises.
    """
    if not isinstance(raw, list) or not raw:
        return None
    chips: list[str] = []
    for item in cast("list[object]", raw):
        if not isinstance(item, str) or item not in KNOWN_CHIPS:
            raise ValueError(
                f"unknown status chip {item!r} in {source} "
                f"(known: {sorted(KNOWN_CHIPS)})"
            )
        chips.append(item)
    return chips


def _chips_from_text(toml_text: str, *, profile: str | None) -> list[str] | None:
    """The chips configured by one TOML *text*, preferring the *profile* section.

    Returns ``None`` when the text is absent/malformed or names no chips, so the
    caller falls through to the next source. Raises only on an unknown chip name
    in a well-formed table (strict, like the groom config)."""
    if not toml_text:
        return None
    try:
        data: dict[str, object] = tomllib.loads(toml_text)
    except tomllib.TOMLDecodeError:
        return None  # fail-soft: a broken file defers to the next source

    # Profile section first (e.g. [profile.ci.tui] status_chips), then base [tui].
    if profile is not None:
        profiles = data.get("profile")
        if isinstance(profiles, dict):
            section = cast("dict[str, object]", profiles).get(profile)
            if isinstance(section, dict):
                tui = cast("dict[str, object]", section).get("tui")
                if isinstance(tui, dict):
                    got = _validated_chips(
                        cast("dict[str, object]", tui).get("status_chips"),
                        f"[profile.{profile}.tui]",
                    )
                    if got is not None:
                        return got

    base_tui = data.get("tui")
    if isinstance(base_tui, dict):
        return _validated_chips(
            cast("dict[str, object]", base_tui).get("status_chips"), "[tui]"
        )
    return None


def load_status_chips(
    global_text: str | None = None,
    project_text: str | None = None,
    *,
    profile: str | None = None,
) -> tuple[str, ...]:
    """Resolve the effective status-line chip order across config sources.

    *global_text* and *project_text* are TOML strings (read from a global and a
    per-project config file; either may be ``None``/empty). *profile* names the
    active profile (typically from ``KINOX_PROFILE``). Returns a tuple of chip
    names ready for :func:`statusline.render`, falling back to
    :data:`statusline.DEFAULT_CHIPS`.
    """
    for text in (project_text, global_text):  # project overrides global
        got = _chips_from_text(text or "", profile=profile)
        if got is not None:
            return tuple(got)
    return DEFAULT_CHIPS
