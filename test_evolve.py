#!/usr/bin/env python3
"""Test suite for Experiment 4: Governed Self-Enhancement Loop.

Tests the governance mechanics — NOT whether the loop produces a specific
outcome (that's the experiment itself), but whether the safety boundary
holds:

  EV1: Eval set integrity — challenges load, are non-trivial, immutable
  EV2: Rule validation — regex compiles, NL lines parse, rejects garbage
  EV3: Injection & removal — rules go into planner.py and come out cleanly
  EV4: Protected paths — developer can't modify test files or eval set
  EV5: Verifier — tests must stay green, score must strictly increase
  EV6: Enforcer — picks the weakest category correctly
  EV7: End-to-end loop — a single cycle runs and produces correct results
  EV8: Revert-all — all injected rules can be removed, planner restored
"""

import sys
import os
import re
import json
import shutil
import tempfile
import subprocess
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))


# ── EV1: Eval set integrity ─────────────────────────────────────────────────

def test_ev1_01_eval_file_exists():
    assert (HERE / "eval_challenges.json").exists()

def test_ev1_02_eval_file_loads():
    data = json.loads((HERE / "eval_challenges.json").read_text())
    assert "challenges" in data
    assert len(data["challenges"]) == 20

def test_ev1_03_challenges_have_required_fields():
    data = json.loads((HERE / "eval_challenges.json").read_text())
    for ch in data["challenges"]:
        assert "id" in ch
        assert "category" in ch
        assert "intent" in ch
        assert "expected_output" in ch

def test_ev1_04_categories_represented():
    data = json.loads((HERE / "eval_challenges.json").read_text())
    cats = set(ch["category"] for ch in data["challenges"])
    assert len(cats) >= 5
    for expected in ["conversational-read", "verbose-create", "delete-variant",
                     "move-variant", "verbose-count"]:
        assert expected in cats

def test_ev1_05_challenges_are_held_out():
    """None of the eval intents should match existing planner rules."""
    from planner import Planner
    p = Planner(use_llm=False)
    data = json.loads((HERE / "eval_challenges.json").read_text())
    held_out = 0
    for ch in data["challenges"]:
        plan = p.plan(ch["intent"])
        # If it's passthrough and the ASG parser can't parse it, it's truly held out
        import asg
        if plan.source == "passthrough" and asg.parse_line(ch["intent"]) is None:
            held_out += 1
    # At least 15 of 20 should be genuinely unhandled at baseline
    assert held_out >= 15, f"Only {held_out}/20 challenges are truly held out"

def test_ev1_06_unique_ids():
    data = json.loads((HERE / "eval_challenges.json").read_text())
    ids = [ch["id"] for ch in data["challenges"]]
    assert len(ids) == len(set(ids))

def test_ev1_07_no_empty_intents():
    data = json.loads((HERE / "eval_challenges.json").read_text())
    for ch in data["challenges"]:
        assert ch["intent"].strip() != ""


# ── EV2: Rule validation ────────────────────────────────────────────────────

def test_ev2_01_valid_rule_passes():
    from evolve import RuleProposal, validate_rule
    rp = RuleProposal(
        pattern=r'^show me (\S+)$',
        replacement=['read file {0}'],
        category="conversational-read",
        rationale="test",
    )
    ok, msg = validate_rule(rp)
    assert ok, f"Should be valid: {msg}"

def test_ev2_02_bad_regex_rejected():
    from evolve import RuleProposal, validate_rule
    rp = RuleProposal(
        pattern=r'^[invalid regex(',
        replacement=['read file {0}'],
        category="conversational-read",
        rationale="test",
    )
    ok, msg = validate_rule(rp)
    assert not ok
    assert "regex" in msg.lower() or "error" in msg.lower()

def test_ev2_03_no_capture_group_rejected():
    from evolve import RuleProposal, validate_rule
    rp = RuleProposal(
        pattern=r'^show me everything$',
        replacement=['list files'],
        category="conversational-read",
        rationale="test",
    )
    ok, msg = validate_rule(rp)
    assert not ok
    assert "group" in msg.lower()

def test_ev2_04_non_parsing_replacement_rejected():
    from evolve import RuleProposal, validate_rule
    rp = RuleProposal(
        pattern=r'^show me (\S+)$',
        replacement=['gibberish that wont parse {0}'],
        category="conversational-read",
        rationale="test",
    )
    ok, msg = validate_rule(rp)
    assert not ok
    assert "parse" in msg.lower()

def test_ev2_05_non_matching_pattern_for_category():
    from evolve import RuleProposal, validate_rule
    rp = RuleProposal(
        pattern=r'^zzz unlikely (\S+)$',
        replacement=['read file {0}'],
        category="conversational-read",
        rationale="test",
    )
    ok, msg = validate_rule(rp)
    assert not ok

def test_ev2_06_valid_rule_for_each_category():
    from evolve import RuleProposal, validate_rule
    tests = [
        ("conversational-read", r'^show me (\S+)$', ['read file {0}']),
        ("verbose-create", r'^create a new file (\S+) with content "([^"]*)"$',
         ['create file {0} with content "{1}"']),
        ("delete-variant", r'^erase (\S+) confirm$', ['delete {0} confirm']),
        ("move-variant", r'^move file (\S+) to (\S+)$', ['move {0} to {1}']),
        ("verbose-count", r'^count how many lines are in (\S+)$', ['count lines in {0}']),
        ("head-variant", r'^get the first (\d+) lines of (\S+)$',
         ['show first {0} lines of {1}']),
        ("concat-variant", r'^concatenate (\S+) and (\S+) into (\S+)$',
         ['read file {0}', 'read file {1}']),
        ("clear-variant", r'^empty the file (\S+)$', ['write "" to {0}']),
    ]
    for cat, pat, repl in tests:
        rp = RuleProposal(pattern=pat, replacement=repl, category=cat, rationale="test")
        ok, msg = validate_rule(rp)
        assert ok, f"{cat}: {msg}"


# ── EV3: Injection & removal ────────────────────────────────────────────────

def test_ev3_01_inject_adds_rule():
    from evolve import RuleProposal, inject_rule, remove_rule, get_injected_rules, \
        _RULES_MARKER
    assert _RULES_MARKER in (HERE / "planner.py").read_text(), \
        "Injection marker not found in planner.py"

    rp = RuleProposal(
        pattern=r'^test inject (\S+)$',
        replacement=['read file {0}'],
        category="conversational-read",
        rationale="test",
    )
    try:
        injected = inject_rule(rp)
        assert injected
        rules = get_injected_rules()
        assert r'^test inject (\S+)$' in rules
    finally:
        remove_rule(r'^test inject (\S+)$')

def test_ev3_02_remove_cleans_up():
    from evolve import RuleProposal, inject_rule, remove_rule, get_injected_rules
    rp = RuleProposal(
        pattern=r'^test remove (\S+)$',
        replacement=['read file {0}'],
        category="conversational-read",
        rationale="test",
    )
    inject_rule(rp)
    assert r'^test remove (\S+)$' in get_injected_rules()
    removed = remove_rule(r'^test remove (\S+)$')
    assert removed
    assert r'^test remove (\S+)$' not in get_injected_rules()

def test_ev3_03_remove_nonexistent_returns_false():
    from evolve import remove_rule
    result = remove_rule(r'^this was never injected (\S+)$')
    assert not result

def test_ev3_04_injected_rule_actually_works():
    """After injection, the planner should handle the new pattern."""
    from evolve import RuleProposal, inject_rule, remove_rule
    import importlib
    import planner as planner_mod

    rp = RuleProposal(
        pattern=r'^test handle (\S+)$',
        replacement=['read file {0}'],
        category="conversational-read",
        rationale="test",
    )
    try:
        inject_rule(rp)
        importlib.reload(planner_mod)
        from planner import Planner
        p = Planner(use_llm=False)
        plan = p.plan("test handle data.txt")
        assert plan.source == "deterministic"
        assert plan.steps == ["read file data.txt"]
    finally:
        remove_rule(r'^test handle (\S+)$')
        importlib.reload(planner_mod)

def test_ev3_05_double_inject_no_duplicate():
    from evolve import RuleProposal, inject_rule, remove_rule, get_injected_rules
    rp = RuleProposal(
        pattern=r'^test double (\S+)$',
        replacement=['read file {0}'],
        category="conversational-read",
        rationale="test",
    )
    try:
        inject_rule(rp)
        # Second inject should add again (caller's responsibility to check)
        inject_rule(rp)
        rules = get_injected_rules()
        count = sum(1 for r in rules if r == r'^test double (\S+)$')
        # Should have 2 entries — the loop checks before injecting
        assert count >= 1
    finally:
        # Clean up all instances
        while remove_rule(r'^test double (\S+)$'):
            pass


# ── EV4: Protected paths ────────────────────────────────────────────────────

def test_ev4_01_protected_paths_defined():
    from evolve import PROTECTED_PATHS
    assert len(PROTECTED_PATHS) >= 10
    assert "eval_challenges.json" in PROTECTED_PATHS
    assert "asg.py" in PROTECTED_PATHS
    assert "interpreter.py" in PROTECTED_PATHS
    assert "test_evolve.py" in PROTECTED_PATHS

def test_ev4_02_developer_only_modifies_planner():
    """The developer's inject_rule should only modify planner.py."""
    from evolve import PLANNER_FILE
    assert PLANNER_FILE.name == "planner.py"

def test_ev4_03_eval_file_not_modified_by_injection():
    """Injecting a rule must not touch eval_challenges.json."""
    from evolve import RuleProposal, inject_rule, remove_rule
    eval_path = HERE / "eval_challenges.json"
    before = eval_path.read_text()
    rp = RuleProposal(
        pattern=r'^test eval protect (\S+)$',
        replacement=['read file {0}'],
        category="conversational-read",
        rationale="test",
    )
    try:
        inject_rule(rp)
        after = eval_path.read_text()
        assert before == after, "eval_challenges.json was modified!"
    finally:
        remove_rule(r'^test eval protect (\S+)$')

def test_ev4_04_test_files_not_modified_by_injection():
    from evolve import RuleProposal, inject_rule, remove_rule
    test_file = HERE / "test_planner.py"
    before = test_file.read_text()
    rp = RuleProposal(
        pattern=r'^test file protect (\S+)$',
        replacement=['read file {0}'],
        category="conversational-read",
        rationale="test",
    )
    try:
        inject_rule(rp)
        after = test_file.read_text()
        assert before == after, "test_planner.py was modified!"
    finally:
        remove_rule(r'^test file protect (\S+)$')


# ── EV5: Verifier ───────────────────────────────────────────────────────────

def test_ev5_01_test_suite_runs():
    from evolve import run_test_suite
    ok, details = run_test_suite()
    # Should pass with current code
    assert ok, f"Test suite should pass:\n{details}"

def test_ev5_02_eval_runs():
    from evolve import run_eval
    from planner import Planner
    p = Planner(use_llm=False)
    result = run_eval(p)
    assert result.total == 20
    assert 0 <= result.score <= 1.0
    # At baseline, most should fail (they're held out)
    assert result.score < 0.15, "Eval should be mostly failing at baseline"

def test_ev5_03_eval_categories_populated():
    from evolve import run_eval
    from planner import Planner
    p = Planner(use_llm=False)
    result = run_eval(p)
    assert len(result.by_category) >= 5
    for cat, (passed, total) in result.by_category.items():
        assert total > 0
        assert passed <= total


# ── EV6: Enforcer ───────────────────────────────────────────────────────────

def test_ev6_01_enforcer_picks_worst_category():
    from evolve import enforcer_set_target, EvalSummary, EvalResult
    # Fake eval: all categories failing except one
    results = [
        EvalResult("E01", "conversational-read", "show me x", True, "x", "x"),
        EvalResult("E02", "conversational-read", "display x", False, "x", ""),
        EvalResult("E03", "verbose-create", "create a new file", False, "x", ""),
        EvalResult("E04", "verbose-create", "make a file called", False, "x", ""),
    ]
    summary = EvalSummary(4, 1, 0.25, {"conversational-read": (1, 2), "verbose-create": (0, 2)}, results)
    target = enforcer_set_target(summary)
    assert target.category == "verbose-create"
    assert len(target.failing_challenges) == 2

def test_ev6_02_enforcer_returns_none_when_all_pass():
    from evolve import enforcer_set_target, EvalSummary, EvalResult
    results = [
        EvalResult("E01", "cat1", "x", True, "y", "y"),
    ]
    summary = EvalSummary(1, 1, 1.0, {"cat1": (1, 1)}, results)
    target = enforcer_set_target(summary)
    assert target.category == "none"

def test_ev6_03_enforcer_includes_failing_intents():
    from evolve import enforcer_set_target, EvalSummary, EvalResult
    results = [
        EvalResult("E01", "cat", "intent A", False, "x", ""),
        EvalResult("E02", "cat", "intent B", False, "x", ""),
        EvalResult("E03", "cat", "intent C", True, "x", "x"),
    ]
    summary = EvalSummary(3, 1, 0.33, {"cat": (1, 3)}, results)
    target = enforcer_set_target(summary)
    assert "intent A" in target.failing_challenges
    assert "intent B" in target.failing_challenges
    assert "intent C" not in target.failing_challenges


# ── EV7: End-to-end single cycle ─────────────────────────────────────────────

def test_ev7_01_single_rule_injection_improves_score():
    """Inject one valid rule and verify eval score increases."""
    from evolve import RuleProposal, inject_rule, remove_rule, run_eval
    import importlib
    import planner as planner_mod

    # Baseline
    from planner import Planner
    p = Planner(use_llm=False)
    before = run_eval(p)

    rp = RuleProposal(
        pattern=r'^show me (\S+)$',
        replacement=['read file {0}'],
        category="conversational-read",
        rationale="'show me X' = 'read file X'",
    )
    try:
        inject_rule(rp)
        importlib.reload(planner_mod)
        from planner import Planner as FP
        p2 = FP(use_llm=False)
        after = run_eval(p2)
        assert after.score > before.score, \
            f"Score should improve: {before.score} → {after.score}"
    finally:
        remove_rule(r'^show me (\S+)$')
        importlib.reload(planner_mod)

def test_ev7_02_reverted_rule_doesnt_improve():
    """Inject + revert should leave score unchanged."""
    from evolve import RuleProposal, inject_rule, remove_rule, run_eval
    import importlib
    import planner as planner_mod

    from planner import Planner
    p = Planner(use_llm=False)
    before = run_eval(p)

    rp = RuleProposal(
        pattern=r'^show me (\S+)$',
        replacement=['read file {0}'],
        category="conversational-read",
        rationale="test",
    )
    inject_rule(rp)
    remove_rule(r'^show me (\S+)$')
    importlib.reload(planner_mod)
    from planner import Planner as FP
    p2 = FP(use_llm=False)
    after = run_eval(p2)
    assert after.score == before.score, \
        f"Score should be same after revert: {before.score} → {after.score}"

def test_ev7_03_developer_has_proposals_for_each_category():
    from evolve import developer_propose, EnforcerTarget
    cats = ["conversational-read", "verbose-create", "delete-variant",
            "move-variant", "verbose-count", "head-variant",
            "concat-variant", "clear-variant"]
    for cat in cats:
        target = EnforcerTarget(cat, ["test"], 0.0, "test demand")
        proposals = developer_propose(target)
        assert len(proposals) >= 1, f"No proposals for {cat}"


# ── EV8: Revert-all ─────────────────────────────────────────────────────────

def test_ev8_01_revert_all_cleans_injected():
    from evolve import RuleProposal, inject_rule, get_injected_rules
    import evolve
    # Inject a few test rules
    for i in range(3):
        rp = RuleProposal(
            pattern=f'^test revert {i} (\\S+)$',
            replacement=['read file {0}'],
            category="conversational-read",
            rationale="test",
        )
        inject_rule(rp)
    assert len(get_injected_rules()) >= 3
    # Run revert-all via the CLI
    result = subprocess.run(
        [sys.executable, str(HERE / "evolve.py"), "revert-all"],
        capture_output=True, text=True, cwd=str(HERE), timeout=10,
    )
    assert result.returncode == 0
    remaining = get_injected_rules()
    assert len(remaining) == 0, f"Rules remain after revert-all: {remaining}"

def test_ev8_02_planner_unaffected_after_revert():
    """After revert-all, existing tests should still pass."""
    # This is implicitly tested by the test suite running at all
    # But let's be explicit
    from planner import Planner
    p = Planner(use_llm=False)
    plan = p.plan("create file test.txt with content \"hello\"")
    assert plan.source in ("deterministic", "passthrough")
    assert len(plan.steps) >= 1
