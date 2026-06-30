"""Tests for products/dashboard/config.py — layered, profile-aware chip config.

Pure (TOML text in, chip tuple out). Fail-soft on absent/malformed, strict on a
well-formed-but-unknown chip.
"""

from __future__ import annotations

import pytest
from products.dashboard.config import load_status_chips
from products.dashboard.statusline import DEFAULT_CHIPS


def test_no_config_uses_default() -> None:
    assert load_status_chips(None, None) == DEFAULT_CHIPS


def test_malformed_toml_falls_soft_to_default() -> None:
    assert load_status_chips("not = = toml [[[", None) == DEFAULT_CHIPS


def test_base_tui_chips() -> None:
    text = '[tui]\nstatus_chips = ["cost", "tokens"]\n'
    assert load_status_chips(text, None) == ("cost", "tokens")


def test_project_overrides_global() -> None:
    g = '[tui]\nstatus_chips = ["tier"]\n'
    p = '[tui]\nstatus_chips = ["cost"]\n'
    assert load_status_chips(g, p) == ("cost",)


def test_profile_overrides_base_within_a_file() -> None:
    text = (
        '[tui]\nstatus_chips = ["tier", "events"]\n'
        '[profile.ci.tui]\nstatus_chips = ["cost"]\n'
    )
    assert load_status_chips(text, None, profile="ci") == ("cost",)
    # Without selecting the profile, the base wins.
    assert load_status_chips(text, None) == ("tier", "events")


def test_profile_precedence_is_project_profile_first() -> None:
    g = '[profile.ci.tui]\nstatus_chips = ["tier"]\n'
    p = '[profile.ci.tui]\nstatus_chips = ["cost", "events"]\n'
    assert load_status_chips(g, p, profile="ci") == ("cost", "events")


def test_empty_list_defers_to_next_source() -> None:
    # An explicit empty list is "not set here" → fall through to global, then default.
    p = "[tui]\nstatus_chips = []\n"
    g = '[tui]\nstatus_chips = ["cost"]\n'
    assert load_status_chips(g, p) == ("cost",)
    assert load_status_chips(None, "[tui]\nstatus_chips = []\n") == DEFAULT_CHIPS


def test_unknown_chip_name_is_rejected() -> None:
    with pytest.raises(ValueError):
        load_status_chips('[tui]\nstatus_chips = ["bogus_chip"]\n', None)


def test_missing_profile_section_falls_back_to_base() -> None:
    text = '[tui]\nstatus_chips = ["tokens"]\n'
    assert load_status_chips(text, None, profile="nonexistent") == ("tokens",)
