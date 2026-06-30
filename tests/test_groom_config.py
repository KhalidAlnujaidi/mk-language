"""Config-driven groom stage ordering (vision §9 #3).

A declarative config.toml selects which groom stages run and in what order.
Pure loader: default when absent/malformed (fail-soft), reject unknown stages.
"""

from __future__ import annotations

import pytest
from products.groom.config import DEFAULT_ORDER, load_stage_order


def test_absent_config_uses_default_order():
    assert load_stage_order(None) == DEFAULT_ORDER


def test_malformed_toml_falls_soft_to_default():
    assert load_stage_order("this is = = not toml [[[") == DEFAULT_ORDER


def test_valid_config_reorders_stages():
    toml = """
[[stage]]
name = "tag"
[[stage]]
name = "redact"
"""
    assert load_stage_order(toml) == ["tag", "redact"]


def test_disabled_stage_is_skipped():
    toml = """
[[stage]]
name = "redact"
enabled = true
[[stage]]
name = "expand"
enabled = false
"""
    assert load_stage_order(toml) == ["redact"]


def test_unknown_stage_name_is_rejected():
    toml = """
[[stage]]
name = "summarize_with_gpt"
"""
    with pytest.raises(ValueError):
        load_stage_order(toml)


def test_valid_toml_without_stage_table_uses_default():
    assert load_stage_order("[other]\nfoo = 1\n") == DEFAULT_ORDER


def test_default_order_includes_deslop():
    # Regression: the deslop stage (added with stop-slop) must be a known stage,
    # in canonical order between context and tag — so a config naming it loads.
    assert DEFAULT_ORDER == ["redact", "expand", "context", "recent_files", "entities", "clipboard", "deslop", "tag", "tool_select"]
    assert load_stage_order('[[stage]]\nname = "deslop"\n') == ["deslop"]
