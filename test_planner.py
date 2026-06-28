#!/usr/bin/env python3
"""Planner test suite — deterministic decomposition + passthrough + LLM integration.

Phase G:  Planner deterministic rules (compound intents → known decomposition)
Phase G+: Conjunction splitting (multi-clause sentences)
Phase H:  Passthrough (single valid intents pass through unchanged)
Phase I:  End-to-end plan→execute (deterministic plans produce correct output)
Phase J:  LLM integration (if Ollama is available — marked as integration)

Run: python3 test_planner.py
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
PYTHON = sys.executable
sys.path.insert(0, str(HERE))

import asg
from planner import (
    Planner, Plan, _try_compound_rules, _split_conjunctions,
    _validate_steps, ASG_VOCABULARY,
)

# ---------------------------------------------------------------------------
# Test infrastructure
# ---------------------------------------------------------------------------

passed = 0
failed = 0
results = []


def run_in_sandbox(fn):
    """Run a function in a temp dir sandbox, restore cwd after."""
    work = Path(tempfile.mkdtemp(prefix="planner_test_"))
    old_cwd = os.getcwd()
    try:
        os.chdir(str(work))
        return fn()
    finally:
        os.chdir(old_cwd)
        shutil.rmtree(work, ignore_errors=True)


def test(name: str, condition: bool, detail: str = ""):
    global passed, failed
    if condition:
        passed += 1
        results.append(f"  ✅ {name}")
    else:
        failed += 1
        results.append(f"  ❌ {name}" + (f" — {detail}" if detail else ""))


# ---------------------------------------------------------------------------
# Phase G: Deterministic compound rules
# ---------------------------------------------------------------------------

def phase_g():
    results.append("\nPhase G: Deterministic Compound Rules")
    planner = Planner(use_llm=False)

    # backup NAME
    plan = planner.plan("backup data.txt")
    test("backup → copy to backup_",
         plan.source == "deterministic" and
         len(plan.steps) == 1 and
         "copy data.txt to backup_data.txt" in plan.steps[0],
         f"got {plan}")

    # backup NAME to DEST
    plan = planner.plan("backup data.txt to archive.txt")
    test("backup-to → copy",
         plan.source == "deterministic" and
         "copy data.txt to archive.txt" in plan.steps[0],
         f"got {plan}")

    # file info NAME → count lines + count words
    plan = planner.plan("file info for report.txt")
    test("file-info → count lines + words",
         plan.source == "deterministic" and len(plan.steps) == 2 and
         plan.steps[0] == "count lines in report.txt" and
         plan.steps[1] == "count words in report.txt",
         f"got {plan}")

    # stats for NAME
    plan = planner.plan("stats for log.txt")
    test("stats → count lines + words",
         plan.source == "deterministic" and len(plan.steps) == 2,
         f"got {plan}")

    # init project NAME
    plan = planner.plan("init project myapp")
    test("init-project → mkdir + create readme",
         plan.source == "deterministic" and len(plan.steps) == 2 and
         "make directory myapp" in plan.steps[0],
         f"got {plan}")

    # create and read NAME with TEXT
    plan = planner.plan('create and read test.txt with content "hello world"')
    test("create-and-read → create + read",
         plan.source == "deterministic" and len(plan.steps) == 2 and
         'create file test.txt with content "hello world"' in plan.steps[0] and
         "read file test.txt" in plan.steps[1],
         f"got {plan}")

    # duplicate NAME
    plan = planner.plan("duplicate notes.txt")
    test("duplicate → copy to copy_of_",
         plan.source == "deterministic" and
         "copy notes.txt to copy_of_notes.txt" in plan.steps[0],
         f"got {plan}")

    # safe delete NAME
    plan = planner.plan("safe delete old.txt")
    test("safe-delete → delete confirm",
         plan.source == "deterministic" and
         plan.steps[0] == "delete old.txt confirm",
         f"got {plan}")

    # inspect NAME → read + count lines + count words
    plan = planner.plan("inspect data.txt")
    test("inspect → read + count lines + count words",
         plan.source == "deterministic" and len(plan.steps) == 3 and
         "read file data.txt" in plan.steps[0],
         f"got {plan}")

    # search for "TEXT"
    plan = planner.plan('search for "error"')
    test('search-for → find files containing',
         plan.source == "deterministic" and
         'find files containing "error"' in plan.steps[0],
         f"got {plan}")

    # grep "PATTERN" in NAME
    plan = planner.plan('grep "warning" in log.txt')
    test("grep → extract lines matching",
         plan.source == "deterministic" and
         'extract lines matching "warning" from log.txt' in plan.steps[0],
         f"got {plan}")

    # head NAME
    plan = planner.plan("head config.txt")
    test("head → show first 10 lines",
         plan.source == "deterministic" and
         "show first 10 lines of config.txt" in plan.steps[0],
         f"got {plan}")

    # head N NAME
    plan = planner.plan("head 5 config.txt")
    test("head-N → show first N lines",
         plan.source == "deterministic" and
         "show first 5 lines of config.txt" in plan.steps[0],
         f"got {plan}")

    # total NAME → sum numbers
    plan = planner.plan("total receipt.txt")
    test("total → sum numbers",
         plan.source == "deterministic" and
         "sum numbers in receipt.txt" in plan.steps[0],
         f"got {plan}")

    # sort NAME
    plan = planner.plan("sort items.txt")
    test("sort → sort lines",
         plan.source == "deterministic" and
         "sort lines in items.txt" in plan.steps[0],
         f"got {plan}")

    # wordcount NAME
    plan = planner.plan("wordcount essay.txt")
    test("wordcount → count words",
         plan.source == "deterministic" and
         "count words in essay.txt" in plan.steps[0],
         f"got {plan}")

    # wc NAME → count lines + count words
    plan = planner.plan("wc data.txt")
    test("wc → count lines + words",
         plan.source == "deterministic" and len(plan.steps) == 2,
         f"got {plan}")


# ---------------------------------------------------------------------------
# Phase G+: Conjunction splitting
# ---------------------------------------------------------------------------

def phase_g_plus():
    results.append("\nPhase G+: Conjunction Splitting")
    planner = Planner(use_llm=False)

    # "X then Y"
    plan = planner.plan('create file a.txt with content "1" then read file a.txt')
    test("then-split",
         plan.source == "deterministic" and len(plan.steps) == 2 and
         'create file a.txt with content "1"' in plan.steps and
         "read file a.txt" in plan.steps,
         f"got {plan}")

    # "X and then Y"
    plan = planner.plan('create file b.txt with content "2" and then read file b.txt')
    test("and-then-split",
         len(plan.steps) == 2,
         f"got {plan}")

    # Semicolon separator
    plan = planner.plan('create file c.txt with content "3"; read file c.txt')
    test("semicolon-split",
         len(plan.steps) == 2,
         f"got {plan}")

    # Arrow separator
    plan = planner.plan('create file d.txt with content "4" -> read file d.txt')
    test("arrow-split",
         len(plan.steps) == 2,
         f"got {plan}")

    # Multi-step chain
    plan = planner.plan(
        'create file x.txt with content "hello" then '
        'append "world" to x.txt then read file x.txt')
    test("multi-chain-split",
         len(plan.steps) == 3,
         f"got {plan} ({len(plan.steps)} steps)")


# ---------------------------------------------------------------------------
# Phase H: Passthrough (single valid intents)
# ---------------------------------------------------------------------------

def phase_h():
    results.append("\nPhase H: Passthrough (Single Valid Intents)")
    planner = Planner(use_llm=False)

    single_intents = [
        'create file test.txt with content "hello"',
        'read file notes.txt',
        'append "more" to data.txt',
        'count lines in log.txt',
        'list files',
        'find files containing "error"',
        'delete old.txt confirm',
        'make directory backups',
        'sum numbers in receipt.txt',
        'sort lines in items.txt',
    ]

    for intent in single_intents:
        plan = planner.plan(intent)
        test(f"passthrough: {intent[:40]}",
             plan.source == "passthrough" and
             len(plan.steps) == 1 and
             plan.steps[0] == intent,
             f"got {plan}")


# ---------------------------------------------------------------------------
# Phase I: End-to-end plan→execute
# ---------------------------------------------------------------------------

def phase_i():
    results.append("\nPhase I: End-to-End Plan→Execute")
    planner = Planner(use_llm=False)

    def e2e_test(name, request, setup_fn, expected_output):
        def run():
            if setup_fn:
                setup_fn()
            output = planner.plan_and_execute(request)
            return output.strip() if output else ""
        try:
            output = run_in_sandbox(run)
            norm_actual = " ".join(output.split())
            norm_expected = " ".join(expected_output.split())
            test(f"e2e: {name}", norm_actual == norm_expected,
                 f"expected '{norm_expected}', got '{norm_actual}'")
        except Exception as e:
            test(f"e2e: {name}", False, f"exception: {e}")

    # backup: create file then backup it → copy should succeed
    e2e_test("backup-data",
             "backup source.txt",
             lambda: _create_file("source.txt", "data"),
             "")

    # file info: create file with known content → count lines + words
    e2e_test("file-info",
             "file info for doc.txt",
             lambda: _create_file("doc.txt", "hello world\nfoo bar"),
             "2 4")

    # stats: same
    e2e_test("stats",
             "stats for data.txt",
             lambda: _create_file("data.txt", "one two three"),
             "1 3")

    # create and read
    e2e_test("create-and-read",
             'create and read test.txt with content "hello"',
             None,
             "hello")

    # inspect: read + count lines + count words
    e2e_test("inspect",
             "inspect page.txt",
             lambda: _create_file("page.txt", "alpha beta\ngamma"),
             "alpha beta gamma 2 3")

    # wc
    e2e_test("wc",
             "wc doc.txt",
             lambda: _create_file("doc.txt", "one two\nthree four five"),
             "2 5")

    # wordcount
    e2e_test("wordcount",
             "wordcount essay.txt",
             lambda: _create_file("essay.txt", "the quick brown fox"),
             "4")

    # head (default 10, but file has fewer)
    e2e_test("head-default",
             "head log.txt",
             lambda: _create_file("log.txt", "first\nsecond"),
             "first second")

    # total (sum numbers)
    e2e_test("total",
             "total receipt.txt",
             lambda: _create_file("receipt.txt", "10 20 5 30"),
             "65")

    # duplicate → copy to copy_of_
    e2e_test("duplicate",
             "duplicate orig.txt",
             lambda: _create_file("orig.txt", "content"),
             "")

    # sort
    e2e_test("sort",
             "sort names.txt",
             lambda: _create_file("names.txt", "charlie\nalice\nbob"),
             "alice bob charlie")

    # grep → extract lines matching
    e2e_test("grep",
             'grep "error" in log.txt',
             lambda: _create_file("log.txt", "error: bad\nok\nerror: timeout"),
             "error: bad error: timeout")


def _create_file(name: str, content: str):
    with open(name, 'w') as f:
        f.write(content)


# ---------------------------------------------------------------------------
# Phase J: LLM integration (optional — only if Ollama available)
# ---------------------------------------------------------------------------

def phase_j():
    results.append("\nPhase J: LLM Integration (requires Ollama)")

    # Check Ollama availability
    try:
        import urllib.request
        req = urllib.request.Request("http://127.0.0.1:11434/api/tags")
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read())
        models = [m["name"] for m in data.get("models", [])]
        if not models:
            results.append("  ⏭️  SKIPPED — no Ollama models available")
            return
    except Exception:
        results.append("  ⏭️  SKIPPED — Ollama not reachable")
        return

    planner = Planner(use_llm=True)

    # Complex request that requires decomposition
    complex_requests = [
        ("create-config-read",
         "Create a config file called app.conf with content 'debug=true', "
         "then read it back to verify"),
        ("log-analysis",
         "Make a log file called server.log with content 'error: crash', "
         "then count how many lines it has, and find which files contain 'error'"),
    ]

    for name, request in complex_requests:
        try:
            plan = planner.plan(request)
            # Verify the plan has valid steps
            valid_steps = _validate_steps(plan.steps)
            test(f"llm:{name}",
                 len(plan.steps) >= 2 and len(valid_steps) >= 2,
                 f"plan={plan.source}, {len(plan.steps)} steps, "
                 f"{len(valid_steps)} valid")
        except Exception as e:
            test(f"llm:{name}", False, f"exception: {e}")


import json  # needed by phase_j


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    print("=" * 60)
    print("MK Planner Test Suite")
    print("=" * 60)

    phase_g()
    phase_g_plus()
    phase_h()
    phase_i()
    phase_j()

    total = passed + failed
    print()
    for r in results:
        print(r)
    print()
    print(f"{'=' * 60}")
    print(f"RESULTS: {passed}/{total} passed"
          + (f", {failed} FAILED" if failed else " — ALL GREEN ✅"))
    print(f"{'=' * 60}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
