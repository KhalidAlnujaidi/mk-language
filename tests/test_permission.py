"""Tests for products/agent/permission.py — layered command-permission rules.

Pure, deterministic resolution (thesis #1), fail-CLOSED tiebreak + hard floor
(thesis #2). No I/O except the tmp-file loader test.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from products.agent import command_safety
from products.agent.permission import (
    Action,
    Layer,
    Rule,
    Ruleset,
    from_dicts,
    level_to_action,
    load_ruleset,
)

_RUN = "run_bash"


def _rs(*rules: Rule) -> Ruleset:
    return Ruleset(rules)


# --- baseline pass-through --------------------------------------------------


def test_empty_ruleset_returns_baseline() -> None:
    d = _rs().resolve(tool=_RUN, command="ls -la", baseline=Action.ALLOW)
    assert d.action is Action.ALLOW
    assert d.rule is None


def test_catastrophic_baseline_is_a_hard_floor() -> None:
    # Even a USER allow-all cannot relax a catastrophic builtin DENY.
    rs = _rs(Rule(Layer.USER, Action.ALLOW))
    d = rs.resolve(tool=_RUN, command="sudo rm -rf /", baseline=Action.DENY)
    assert d.action is Action.DENY
    assert d.rule is None


# --- layer precedence -------------------------------------------------------


def test_user_overrides_agent() -> None:
    rs = _rs(
        Rule(Layer.AGENT, Action.DENY, command_prefix="git push"),
        Rule(Layer.USER, Action.ALLOW, command_prefix="git push"),
    )
    d = rs.resolve(tool=_RUN, command="git push --force", baseline=Action.ASK)
    assert d.action is Action.ALLOW  # user is sovereign
    assert d.rule is not None and d.rule.layer is Layer.USER


def test_user_can_tighten_a_safe_command_to_deny() -> None:
    rs = _rs(Rule(Layer.USER, Action.DENY, command_prefix="npm publish"))
    d = rs.resolve(
        tool=_RUN, command="npm publish --access public", baseline=Action.ALLOW
    )
    assert d.action is Action.DENY


def test_user_can_downgrade_ask_to_allow() -> None:
    rs = _rs(Rule(Layer.USER, Action.ALLOW, command_prefix="git push"))
    d = rs.resolve(tool=_RUN, command="git push -f", baseline=Action.ASK)
    assert d.action is Action.ALLOW


# --- specificity + tiebreak -------------------------------------------------


def test_more_specific_rule_wins_within_a_layer() -> None:
    rs = _rs(
        Rule(Layer.USER, Action.ALLOW),  # catch-all
        Rule(Layer.USER, Action.DENY, command_prefix="git push"),  # specific
    )
    d = rs.resolve(tool=_RUN, command="git push origin", baseline=Action.ALLOW)
    assert d.action is Action.DENY


def test_exact_tie_breaks_to_safer_action() -> None:
    # Same layer, same specificity (both bare catch-alls) → DENY wins.
    rs = _rs(Rule(Layer.USER, Action.ALLOW), Rule(Layer.USER, Action.DENY))
    d = rs.resolve(tool=_RUN, command="anything", baseline=Action.ALLOW)
    assert d.action is Action.DENY


# --- matching semantics -----------------------------------------------------


def test_arity_aware_prefix_does_not_overmatch() -> None:
    rs = _rs(Rule(Layer.USER, Action.DENY, command_prefix="git push"))
    # "git status" must NOT be caught by a "git push" rule.
    d = rs.resolve(tool=_RUN, command="git status -s", baseline=Action.ALLOW)
    assert d.action is Action.ALLOW


def test_tool_scoping() -> None:
    rs = _rs(Rule(Layer.USER, Action.DENY, tool="write_file"))
    # The rule is scoped to write_file, so run_bash is unaffected.
    d = rs.resolve(tool=_RUN, command="ls", baseline=Action.ALLOW)
    assert d.action is Action.ALLOW


# --- level mapping ----------------------------------------------------------


def test_level_to_action_mapping() -> None:
    assert level_to_action(command_safety.Level.SAFE) is Action.ALLOW
    assert level_to_action(command_safety.Level.ASK) is Action.ASK
    assert level_to_action(command_safety.Level.DENY) is Action.DENY


# --- loaders ----------------------------------------------------------------


def test_from_dicts_strict_on_bad_action() -> None:
    with pytest.raises(ValueError):
        from_dicts([{"layer": "user", "action": "nonsense"}])


def test_load_ruleset_missing_file_is_empty_failsoft(tmp_path: Path) -> None:
    rs = load_ruleset(tmp_path / "absent.toml")
    assert rs.rules == ()


def test_load_ruleset_parses_toml(tmp_path: Path) -> None:
    p = tmp_path / "permissions.toml"
    p.write_text(
        '[[rules]]\nlayer = "user"\naction = "deny"\n'
        'tool = "run_bash"\ncommand = "git push"\n'
    )
    rs = load_ruleset(p)
    assert len(rs.rules) == 1
    r = rs.rules[0]
    assert r.layer is Layer.USER and r.action is Action.DENY
    assert r.command_prefix == "git push"
    d = rs.resolve(tool=_RUN, command="git push origin main", baseline=Action.ALLOW)
    assert d.action is Action.DENY


# --- guard integration ------------------------------------------------------


def test_project_root_guard_enforces_user_deny_rule(tmp_path: Path) -> None:
    from products.agent.tools import project_root_guard

    rs = _rs(Rule(Layer.USER, Action.DENY, tool=_RUN, command_prefix="git push"))
    guard = project_root_guard(tmp_path, ruleset=rs)

    import pytest
    from products.agent.loop import GuardBlocked

    # A user-DENYed command is refused...
    with pytest.raises(GuardBlocked) as exc_info:
        guard(_RUN, '{"command": "git push --force origin main"}')
    assert "refused" in str(exc_info.value)
    # ...while an unrelated command still passes (no regression).
    assert guard(_RUN, '{"command": "git status"}') is None


def test_project_root_guard_without_ruleset_is_unchanged(tmp_path: Path) -> None:
    from products.agent.tools import project_root_guard

    guard = project_root_guard(tmp_path)  # ruleset defaults to None
    # A non-catastrophic command still passes exactly as before.
    assert guard(_RUN, '{"command": "git push origin main"}') is None

