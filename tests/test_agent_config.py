"""Tests for products/agent/config.py — layered agent config."""

from __future__ import annotations

from products.agent.config import load_ruleset, load_token_budget


def test_no_config_yields_none() -> None:
    assert load_token_budget(None, None) is None
    assert load_ruleset(None, None) is None


def test_malformed_toml_yields_none() -> None:
    assert load_token_budget("not toml [[[", None) is None


def test_budget_from_base_agent() -> None:
    text = '[agent]\ntoken_budget = 5000\n'
    b = load_token_budget(text, None)
    assert b is not None
    assert b.limit == 5000


def test_budget_project_overrides_global() -> None:
    g = '[agent]\ntoken_budget = 5000\n'
    p = '[agent]\ntoken_budget = 1000\n'
    b = load_token_budget(g, p)
    assert b is not None
    assert b.limit == 1000


def test_budget_profile_overrides_base() -> None:
    text = (
        '[agent]\ntoken_budget = 5000\n'
        '[profile.ci.agent]\ntoken_budget = 1000\n'
    )
    b = load_token_budget(text, None, profile="ci")
    assert b is not None
    assert b.limit == 1000

    # Without profile, base wins
    b2 = load_token_budget(text, None)
    assert b2 is not None
    assert b2.limit == 5000


def test_ruleset_from_base_agent() -> None:
    text = '''
[agent]
[[agent.rules]]
layer = "user"
action = "allow"
command = "git log"
'''
    r = load_ruleset(text, None)
    assert r is not None
    assert len(r.rules) == 1
    assert r.rules[0].command_prefix == "git log"


def test_ruleset_profile_overrides_base() -> None:
    text = '''
[agent]
[[agent.rules]]
layer = "user"
action = "allow"
command = "git log"

[profile.ci.agent]
[[profile.ci.agent.rules]]
layer = "user"
action = "deny"
command = "ls"
'''
    r = load_ruleset(text, None, profile="ci")
    assert r is not None
