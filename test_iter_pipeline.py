#!/usr/bin/env python3
"""Experiment 2: Pipeline + Iteration Composition Tests

Tests that combine iteration (for each *.EXT) with pipeline capture (set var +
write/append). These are the most complex plans in the system — they compose
ForEachFile nodes with SetVar + AppendFile/WriteFile bodies.

Patterns tested:
  - "for each *.txt, count lines and append to summary"
  - "for each *.txt, count words and append to summary"
  - "for each *.txt, sum numbers and append to total"
  - "count lines in all *.txt and save to summary"
  - "sum numbers in all *.txt and save to total"
  - "count words in all *.txt and save to summary"
  - "backup all *.txt to <dir>"
  - "for each *.txt, extract PATTERN and save to out"
  - "count lines in all *.txt and write total to total"
  - "inspect all *.txt" → multi-op per file
  - "backup all *.txt" → copy each

Each pattern tested for:
  1. Plan decomposition (source=iteration, correct structure)
  2. End-to-end execution in a sandbox (correct output)
"""

import sys
import os
import tempfile
import io
from contextlib import redirect_stdout

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import asg
from planner import Planner
from interpreter import execute

PASS = 0
FAIL = 0
RESULTS = []


def test(name, condition, detail=""):
    global PASS, FAIL
    if condition:
        PASS += 1
        RESULTS.append(f"  ✅ {name}")
    else:
        FAIL += 1
        RESULTS.append(f"  ❌ {name} — {detail}")


def make_sandbox(files: dict) -> str:
    """Create a temp dir with the given files. Returns the dir path."""
    d = tempfile.mkdtemp()
    for name, content in files.items():
        path = os.path.join(d, name)
        os.makedirs(os.path.dirname(path), exist_ok=True) if os.path.dirname(name) else None
        with open(path, 'w') as f:
            f.write(content)
    return d


def run_in_dir(plan, d):
    """Execute a plan in directory d, capture stdout."""
    old = os.getcwd()
    os.chdir(d)
    try:
        buf = []
        nodes = plan.to_nodes()
        execute(nodes)
        return execute(nodes)
    finally:
        os.chdir(old)


# ---------------------------------------------------------------------------
# Phase IP1: Plan decomposition tests
# ---------------------------------------------------------------------------

def phase_ip1():
    RESULTS.append("\nPhase IP1: Iteration+Pipeline Plan Decomposition")
    planner = Planner(use_llm=False)

    # "for each *.txt, count lines and append to summary"
    plan = planner.plan("for each *.txt, count lines and append to summary.txt")
    test("plan: for each count lines append → iteration",
         plan.source == "iteration", f"got source={plan.source}")
    test("plan: for each count lines append → has pre-step",
         len(plan.steps) >= 1 and "summary.txt" in plan.steps[0],
         f"got steps={plan.steps}")
    test("plan: for each count lines append → ForEachFile node",
         len(plan.extra_nodes) == 1 and isinstance(plan.extra_nodes[0], asg.ForEachFile),
         f"got extra={plan.extra_nodes}")
    if plan.extra_nodes:
        node = plan.extra_nodes[0]
        test("plan: for each count lines → glob *.txt",
             node.glob_pattern == "*.txt", f"got glob={node.glob_pattern}")
        test("plan: for each count lines → 2 body ops (SetVar+Append)",
             len(node.body_template) == 2, f"got body={len(node.body_template)}")
        test("plan: for each count lines → body[0] is SetVar",
             isinstance(node.body_template[0], asg.SetVar),
             f"got body[0]={type(node.body_template[0]).__name__}")

    # "for each *.txt, count words and append to summary"
    plan = planner.plan("for each *.txt, count words and append to summary.txt")
    test("plan: for each count words append → iteration",
         plan.source == "iteration", f"got source={plan.source}")
    test("plan: for each count words → has pre-step",
         len(plan.steps) >= 1, f"got steps={plan.steps}")

    # "for each *.txt, sum numbers and append to total"
    plan = planner.plan("for each *.txt, sum numbers and append to total.txt")
    test("plan: for each sum numbers append → iteration",
         plan.source == "iteration", f"got source={plan.source}")

    # "count lines in all *.txt and save to summary"
    plan = planner.plan("count lines in all *.txt and save to summary.txt")
    test("plan: count lines in all save → iteration",
         plan.source == "iteration", f"got source={plan.source}")

    # "sum numbers in all *.txt and save to total"
    plan = planner.plan("sum numbers in all *.txt and save to total.txt")
    test("plan: sum numbers in all save → iteration",
         plan.source == "iteration", f"got source={plan.source}")

    # "count words in all *.txt and save to summary"
    plan = planner.plan("count words in all *.txt and save to summary.txt")
    test("plan: count words in all save → iteration",
         plan.source == "iteration", f"got source={plan.source}")

    # "backup all *.txt to <dir>"
    plan = planner.plan("backup all *.txt to backups")
    test("plan: backup all to dir → iteration",
         plan.source == "iteration", f"got source={plan.source}")
    if plan.extra_nodes:
        node = plan.extra_nodes[0]
        test("plan: backup all → body[0] is CopyFile",
             isinstance(node.body_template[0], asg.CopyFile),
             f"got body[0]={type(node.body_template[0]).__name__}")

    # "for each *.txt, extract PATTERN and save to out"
    plan = planner.plan('for each *.txt, extract "error" and save to out.txt')
    test("plan: for each extract save → iteration",
         plan.source == "iteration", f"got source={plan.source}")

    # "inspect all *.txt" → 3 body nodes
    plan = planner.plan("inspect all *.txt")
    test("plan: inspect all → iteration",
         plan.source == "iteration", f"got source={plan.source}")
    if plan.extra_nodes:
        test("plan: inspect all → 3 body ops",
             len(plan.extra_nodes[0].body_template) == 3,
             f"got body len={len(plan.extra_nodes[0].body_template)}")

    # "backup all *.txt" → CopyFile body
    plan = planner.plan("backup all *.txt")
    test("plan: backup all (no dir) → iteration",
         plan.source == "iteration", f"got source={plan.source}")
    if plan.extra_nodes:
        test("plan: backup all → CopyFile body",
             isinstance(plan.extra_nodes[0].body_template[0], asg.CopyFile),
             f"got body[0]={type(plan.extra_nodes[0].body_template[0]).__name__}")


# ---------------------------------------------------------------------------
# Phase IP2: End-to-end execution tests
# ---------------------------------------------------------------------------

def phase_ip2():
    RESULTS.append("\nPhase IP2: Iteration+Pipeline End-to-End Execution")

    # --- Test: for each *.txt, count lines and append to summary ---
    d = make_sandbox({
        'a.txt': 'line1\nline2\n',
        'b.txt': 'x\ny\nz\n',
    })
    planner = Planner(use_llm=False)
    plan = planner.plan("for each *.txt, count lines and append to summary.txt")
    output = run_in_dir(plan, d)
    summary_path = os.path.join(d, "summary.txt")
    if os.path.exists(summary_path):
        content = open(summary_path).read().strip()
        lines = content.split('\n') if content else []
        test("e2e: count lines append → has values",
             len(lines) >= 2, f"got content={content!r}")
        test("e2e: count lines append → a.txt=2",
             '2' in lines, f"got lines={lines}")
        test("e2e: count lines append → b.txt=3",
             '3' in lines, f"got lines={lines}")
    else:
        test("e2e: count lines append → file created", False, "file not found")
    import shutil; shutil.rmtree(d)

    # --- Test: for each *.txt, count words and append to summary ---
    d = make_sandbox({
        'a.txt': 'hello world\n',
        'b.txt': 'foo bar baz\n',
    })
    plan = planner.plan("for each *.txt, count words and append to summary.txt")
    output = run_in_dir(plan, d)
    summary_path = os.path.join(d, "summary.txt")
    if os.path.exists(summary_path):
        content = open(summary_path).read().strip()
        lines = content.split('\n') if content else []
        test("e2e: count words append → a.txt=2",
             '2' in lines, f"got lines={lines}")
        test("e2e: count words append → b.txt=3",
             '3' in lines, f"got lines={lines}")
    else:
        test("e2e: count words append → file created", False, "file not found")
    shutil.rmtree(d)

    # --- Test: for each *.txt, sum numbers and append to total ---
    d = make_sandbox({
        'nums1.txt': '10\n20\n30\n',
        'nums2.txt': '5\n15\n',
    })
    plan = planner.plan("for each *.txt, sum numbers and append to total.txt")
    output = run_in_dir(plan, d)
    total_path = os.path.join(d, "total.txt")
    if os.path.exists(total_path):
        content = open(total_path).read().strip()
        lines = content.split('\n') if content else []
        test("e2e: sum numbers append → nums1=60",
             '60' in lines, f"got lines={lines}")
        test("e2e: sum numbers append → nums2=20",
             '20' in lines, f"got lines={lines}")
    else:
        test("e2e: sum numbers append → file created", False, "file not found")
    shutil.rmtree(d)

    # --- Test: count lines in all *.txt and save to summary ---
    d = make_sandbox({
        'x.txt': 'a\nb\nc\nd\n',
        'y.txt': '1\n2\n',
    })
    plan = planner.plan("count lines in all *.txt and save to summary.txt")
    output = run_in_dir(plan, d)
    summary_path = os.path.join(d, "summary.txt")
    if os.path.exists(summary_path):
        content = open(summary_path).read().strip()
        lines = content.split('\n') if content else []
        test("e2e: count lines in all save → x=4",
             '4' in lines, f"got lines={lines}")
        test("e2e: count lines in all save → y=2",
             '2' in lines, f"got lines={lines}")
    else:
        test("e2e: count lines in all save → file created", False, "file not found")
    shutil.rmtree(d)

    # --- Test: backup all *.txt to dir ---
    d = make_sandbox({
        'a.txt': 'hello',
        'b.txt': 'world',
    })
    os.makedirs(os.path.join(d, 'backups'), exist_ok=True)
    plan = planner.plan("backup all *.txt to backups")
    output = run_in_dir(plan, d)
    ba = os.path.join(d, 'backups', 'a.txt')
    bb = os.path.join(d, 'backups', 'b.txt')
    test("e2e: backup all to dir → a.txt copied",
         os.path.exists(ba), f"path={ba}")
    test("e2e: backup all to dir → b.txt copied",
         os.path.exists(bb), f"path={bb}")
    if os.path.exists(ba):
        test("e2e: backup all to dir → a.txt content correct",
             open(ba).read() == 'hello', f"got={open(ba).read()!r}")
    shutil.rmtree(d)

    # --- Test: inspect all *.txt ---
    d = make_sandbox({
        'data.txt': 'hello\nworld\n',
    })
    plan = planner.plan("inspect all *.txt")
    output = run_in_dir(plan, d)
    test("e2e: inspect all → output has read content",
         'hello' in output or 'hello world' in output, f"got={output!r}")
    test("e2e: inspect all → output has line count",
         '2' in output, f"got={output!r}")
    test("e2e: inspect all → output has word count",
         '2' in output, f"got={output!r}")
    shutil.rmtree(d)

    # --- Test: backup all *.txt (to backup_NAME) ---
    d = make_sandbox({
        'original.txt': 'content here',
    })
    plan = planner.plan("backup all *.txt")
    output = run_in_dir(plan, d)
    backup_path = os.path.join(d, 'backup_original.txt')
    test("e2e: backup all → backup_original.txt created",
         os.path.exists(backup_path), f"path={backup_path}")
    if os.path.exists(backup_path):
        test("e2e: backup all → content matches",
             open(backup_path).read() == 'content here',
             f"got={open(backup_path).read()!r}")
    shutil.rmtree(d)


# ---------------------------------------------------------------------------
# Phase IP3: Edge cases
# ---------------------------------------------------------------------------

def phase_ip3():
    RESULTS.append("\nPhase IP3: Iteration+Pipeline Edge Cases")

    # --- No matching files ---
    d = make_sandbox({})
    planner = Planner(use_llm=False)
    plan = planner.plan("for each *.txt, count lines and append to summary.txt")
    output = run_in_dir(plan, d)
    summary_path = os.path.join(d, "summary.txt")
    if os.path.exists(summary_path):
        content = open(summary_path).read().strip()
        test("edge: no matching files → empty output",
             content == '', f"got content={content!r}")
    else:
        test("edge: no matching files → pre-step creates file",
             os.path.exists(summary_path), "file not found")
    import shutil; shutil.rmtree(d)

    # --- Single file ---
    d = make_sandbox({'only.txt': 'one\ntwo\n'})
    plan = planner.plan("for each *.txt, count lines and append to summary.txt")
    output = run_in_dir(plan, d)
    summary_path = os.path.join(d, "summary.txt")
    if os.path.exists(summary_path):
        content = open(summary_path).read().strip()
        test("edge: single file → one value",
             content == '2', f"got content={content!r}")
    else:
        test("edge: single file → file created", False)
    shutil.rmtree(d)

    # --- Summary file excluded from iteration ---
    d = make_sandbox({
        'a.txt': 'x\n',
        'b.txt': 'y\nz\n',
    })
    plan = planner.plan("for each *.txt, count lines and append to summary.txt")
    output = run_in_dir(plan, d)
    summary_path = os.path.join(d, "summary.txt")
    if os.path.exists(summary_path):
        content = open(summary_path).read().strip()
        lines = content.split('\n') if content else []
        test("edge: summary.txt excluded → exactly 2 values (not 3)",
             len(lines) == 2, f"got {len(lines)} values: {lines}")
    else:
        test("edge: summary.txt excluded", False)
    shutil.rmtree(d)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    print("=" * 60)
    print("Experiment 2: Pipeline + Iteration Composition Tests")
    print("=" * 60)

    phase_ip1()
    phase_ip2()
    phase_ip3()

    print("\n".join(RESULTS))
    print()
    print("=" * 60)
    total = PASS + FAIL
    print(f"RESULTS: {PASS}/{total} passed", end="")
    if FAIL == 0:
        print(" — ALL GREEN ✅")
    else:
        print(f", {FAIL} FAILED ❌")
    print("=" * 60)
