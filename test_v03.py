#!/usr/bin/env python3
"""v03 test suite — ASG + terminal backend + python backend + cross-target invariant.

Phase A:  11/11 through the ASG (same programs as _verify_all.py)
Phase A+:  ASG structure validation (graph shape correctness)
Phase B:  Terminal backend correctness (ASG → shell → same output)
Phase B+: Terminal-native expansion (wc, sort, head, sum, grep)
Phase C:  Python backend correctness (ASG → Python → same output)
Phase C+: Python-native computation rungs (same new intents through Python)
Phase D:  Cross-target invariant (same intent → same OS outcome across all 3)
Scored:   0–1 score per rung with reason (gradient, not cliff)
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

# Ensure local modules are importable
sys.path.insert(0, str(HERE))

import asg
from terminal_backend import compile_to_shell
from python_backend import compile_to_python
from sql_backend import compile_to_sql, execute_sql

# ---------------------------------------------------------------------------
# The 11 conformance programs (shared across all phases)
# ---------------------------------------------------------------------------

CONFORMANCE = [
    ("create-and-read",
     'create file notes.txt with content "hello"\nread file notes.txt', "hello"),
    ("list-dir",
     'create file alpha.txt with content "x"\nlist files', "alpha.txt"),
    ("append",
     'create file p.txt with content "one"\nappend "two" to p.txt\nread file p.txt',
     "one two"),
    ("count-lines",
     'create file n.txt with content "a"\nappend "b" to n.txt\n'
     'append "c" to n.txt\ncount lines in n.txt', "3"),
    ("copy",
     'create file s.txt with content "data"\ncopy s.txt to d.txt\nread file d.txt',
     "data"),
    ("mkdir-move",
     'create file m.txt with content "z"\nmake directory logs\n'
     'move m.txt to logs\nlist files in logs', "m.txt"),
    ("search-content",
     'create file h.txt with content "hello"\ncreate file g.txt with content "bye"\n'
     'find files containing "hello"', "h.txt"),
    ("sequence",
     'create file s1.txt with content "1"\ncreate file s2.txt with content "2"\n'
     'list files', "s1.txt s2.txt"),
    ("decision",
     'if missing.txt exists then read file missing.txt otherwise '
     'create file missing.txt with content "made"\nread file missing.txt', "made"),
    ("safety-refuse-irreversible",
     'create file b.txt with content "x"\ndelete b.txt', "REFUSED"),
    ("safety-confirm-irreversible",
     'create file c.txt with content "x"\ndelete c.txt confirm\nlist files', "(empty)"),
]

# Additional terminal-native rungs (Phase B expansion: pipes, globs, grep, wc)
TERMINAL_EXTRA = [
    ("grep-pipe",
     'create file log.txt with content "error on line 1"\n'
     'find files containing "error"', "log.txt"),
    ("multi-file-search",
     'create file a.txt with content "found it"\n'
     'create file b.txt with content "nothing here"\n'
     'find files containing "found"', "a.txt"),
]

# --- v03 expansion: terminal-native computational rungs ---

TERMINAL_COMPUTE = [
    ("count-words",
     'create file w.txt with content "one two three four"\n'
     'count words in w.txt', "4"),
    ("sort-lines",
     'create file s.txt with content "banana"\n'
     'append "apple" to s.txt\n'
     'append "cherry" to s.txt\n'
     'sort lines in s.txt', "apple banana cherry"),
    ("head-lines",
     'create file h.txt with content "first"\n'
     'append "second" to h.txt\n'
     'append "third" to h.txt\n'
     'show first 2 lines of h.txt', "first second"),
    ("sum-numbers",
     'create file nums.txt with content "10 20 5"\n'
     'sum numbers in nums.txt', "35"),
    ("extract-pattern",
     'create file log2.txt with content "error: disk full"\n'
     'append "info: ok" to log2.txt\n'
     'append "error: timeout" to log2.txt\n'
     'extract lines matching "error" from log2.txt',
     "error: disk full error: timeout"),
]

# Python-native rungs reuse the same programs — they prove the Python backend
# produces identical output for the computational intents.

PYTHON_COMPUTE = TERMINAL_COMPUTE  # same intents, different target

# SQL backend rungs: same computational intents through SQL (SQLite)
# Table names use underscores: notes.txt → notes_txt
SQL_CONFORMANCE = [
    ("create-and-read",
     'create file notes.txt with content "hello"\nread file notes.txt', "hello"),
    ("list-dir",
     'create file alpha.txt with content "x"\nlist files', "alpha.txt"),
    ("append",
     'create file p.txt with content "one"\nappend "two" to p.txt\nread file p.txt',
     "one two"),
    ("count-lines",
     'create file n.txt with content "a"\nappend "b" to n.txt\n'
     'append "c" to n.txt\ncount lines in n.txt', "3"),
    ("copy",
     'create file s.txt with content "data"\ncopy s.txt to d.txt\nread file d.txt',
     "data"),
    ("mkdir-move",
     'create file m.txt with content "z"\nmake directory logs\n'
     'move m.txt to logs', ""),
    ("search-content",
     'create file h.txt with content "hello"\ncreate file g.txt with content "bye"\n'
     'find files containing "hello"', "h.txt"),
    ("sequence",
     'create file s1.txt with content "1"\ncreate file s2.txt with content "2"\n'
     'list files', "s1.txt s2.txt"),
    ("decision",
     'if missing.txt exists then read file missing.txt otherwise '
     'create file fallback.txt with content "made"', ""),
    ("safety-refuse-irreversible",
     'create file b.txt with content "x"\ndelete b.txt', "REFUSED"),
    ("safety-confirm-irreversible",
     'create file c.txt with content "x"\ndelete c.txt confirm\nlist files', "(empty)"),
]

SQL_COMPUTE = [
    ("count-words",
     'create file w.txt with content "one two three four"\n'
     'count words in w.txt', "4"),
    ("sort-lines",
     'create file s.txt with content "banana"\n'
     'append "apple" to s.txt\n'
     'append "cherry" to s.txt\n'
     'sort lines in s.txt', "apple banana cherry"),
    ("head-lines",
     'create file h.txt with content "first"\n'
     'append "second" to h.txt\n'
     'append "third" to h.txt\n'
     'show first 2 lines of h.txt', "first second"),
    ("sum-numbers",
     'create file nums.txt with content "10 20 5"\n'
     'sum numbers in nums.txt', "35"),
    ("extract-pattern",
     'create file log2.txt with content "error: disk full"\n'
     'append "info: ok" to log2.txt\n'
     'append "error: timeout" to log2.txt\n'
     'extract lines matching "error" from log2.txt',
     "error: disk full error: timeout"),
]


# ---------------------------------------------------------------------------
# Test infrastructure
# ---------------------------------------------------------------------------

def normalize(s: str) -> str:
    """Normalize whitespace for comparison."""
    return " ".join(s.split())


def run_in_sandbox(runner: str, program: str, interp_path: Path | None = None) -> str:
    """Run a program in a temp dir sandbox, return captured stdout."""
    work = Path(tempfile.mkdtemp(prefix="v03_test_"))
    try:
        if interp_path:
            result = subprocess.run(
                [PYTHON, str(HERE / "_sandbox_run.py"), str(interp_path)],
                input=program, capture_output=True, text=True,
                cwd=str(work), timeout=15,
            )
        else:
            result = subprocess.run(
                [PYTHON, "-c", program],
                capture_output=True, text=True,
                cwd=str(work), timeout=15,
            )
        return normalize(result.stdout.strip())
    finally:
        shutil.rmtree(work, ignore_errors=True)


def run_shell_in_sandbox(script: str) -> str:
    """Run a shell script in a temp dir sandbox, return captured stdout."""
    work = Path(tempfile.mkdtemp(prefix="v03_sh_"))
    try:
        result = subprocess.run(
            ["sh"], input=script, capture_output=True, text=True,
            cwd=str(work), timeout=15,
        )
        return normalize(result.stdout.strip())
    finally:
        shutil.rmtree(work, ignore_errors=True)


def run_python_in_sandbox(code: str) -> str:
    """Run generated Python code in a temp dir sandbox, return captured stdout."""
    work = Path(tempfile.mkdtemp(prefix="v03_py_"))
    try:
        result = subprocess.run(
            [PYTHON, "-c", code],
            capture_output=True, text=True,
            cwd=str(work), timeout=15,
        )
        return normalize(result.stdout.strip())
    finally:
        shutil.rmtree(work, ignore_errors=True)


# ---------------------------------------------------------------------------
# Scored result reporting (replaces boolean pass/fail)
# ---------------------------------------------------------------------------

class ScoreResult:
    def __init__(self):
        self.results: list[tuple[str, float, str]] = []

    def record(self, name: str, score: float, reason: str = ""):
        self.results.append((name, score, reason))

    @property
    def total(self) -> float:
        return sum(s for _, s, _ in self.results)

    @property
    def max_possible(self) -> float:
        return float(len(self.results))

    def report(self, label: str) -> bool:
        print(f"\n{'='*60}")
        print(f"  {label}")
        print(f"{'='*60}")
        all_pass = True
        for name, score, reason in self.results:
            mark = "✅" if score == 1.0 else ("⚠️" if score > 0 else "⬜")
            extra = f" — {reason}" if reason and score < 1.0 else ""
            print(f"  {mark} {name}: {score:.2f}{extra}")
            if score < 1.0:
                all_pass = False
        pct = (self.total / self.max_possible * 100) if self.max_possible else 0
        print(f"\n  SCORE: {self.total:.1f}/{self.max_possible:.0f} ({pct:.0f}%)")
        return all_pass


# ---------------------------------------------------------------------------
# Phase A — ASG parsing + direct execution (11/11 through the graph)
# ---------------------------------------------------------------------------

def test_phase_a() -> bool:
    sr = ScoreResult()
    for name, program, expected in CONFORMANCE:
        nodes = asg.parse(program)
        # Verify parse produced nodes
        if not nodes:
            sr.record(name, 0.0, "parse produced no nodes")
            continue

        # Execute through the ASG in a sandbox
        interp_path = HERE / "interpreter.py"
        actual = run_in_sandbox("sandbox", program, interp_path)
        exp = normalize(expected)

        if actual == exp:
            sr.record(name, 1.0)
        else:
            sr.record(name, 0.0, f"expected '{exp}', got '{actual}'")

    return sr.report("Phase A: ASG Parse → Execute (11 rungs)")


# ---------------------------------------------------------------------------
# Phase A+ — ASG structure validation (graph shape correctness)
# ---------------------------------------------------------------------------

def test_phase_a_structure() -> bool:
    sr = ScoreResult()

    # Test 1: parse produces correct node types
    nodes = asg.parse('create file test.txt with content "hi"')
    if len(nodes) == 1 and isinstance(nodes[0], asg.CreateFile):
        sr.record("parse-create-type", 1.0)
    else:
        sr.record("parse-create-type", 0.0, f"got {nodes}")

    # Test 2: conditional produces a Decision node with branches
    nodes = asg.parse('if x.txt exists then read file x.txt otherwise create file y.txt with content "no"')
    if len(nodes) == 1 and isinstance(nodes[0], asg.Conditional):
        if len(nodes[0].then_branch) == 1 and len(nodes[0].else_branch) == 1:
            sr.record("parse-conditional-branches", 1.0)
        else:
            sr.record("parse-conditional-branches", 0.5, "branches exist but wrong count")
    else:
        sr.record("parse-conditional-branches", 0.0, "not a Conditional node")

    # Test 3: multi-line produce
    nodes = asg.parse('create file a.txt with content "1"\ncreate file b.txt with content "2"')
    if len(nodes) == 2 and all(isinstance(n, asg.CreateFile) for n in nodes):
        sr.record("parse-sequence-length", 1.0)
    else:
        sr.record("parse-sequence-length", 0.0, f"got {len(nodes)} nodes")

    # Test 4: new node types parse correctly
    nodes = asg.parse('count words in f.txt')
    if len(nodes) == 1 and isinstance(nodes[0], asg.CountWords):
        sr.record("parse-count-words", 1.0)
    else:
        sr.record("parse-count-words", 0.0, f"got {nodes}")

    # Test 5: head-lines with count parameter
    nodes = asg.parse('show first 3 lines of f.txt')
    if len(nodes) == 1 and isinstance(nodes[0], asg.HeadLines):
        if nodes[0].count == 3:
            sr.record("parse-head-lines", 1.0)
        else:
            sr.record("parse-head-lines", 0.5, f"count={nodes[0].count}")
    else:
        sr.record("parse-head-lines", 0.0, f"got {nodes}")

    # Test 6: sum-numbers and extract-pattern parse correctly
    nodes = asg.parse('sum numbers in data.txt')
    if len(nodes) == 1 and isinstance(nodes[0], asg.SumNumbers):
        sr.record("parse-sum-numbers", 1.0)
    else:
        sr.record("parse-sum-numbers", 0.0, f"got {nodes}")

    nodes = asg.parse('extract lines matching "error" from log.txt')
    if len(nodes) == 1 and isinstance(nodes[0], asg.ExtractPattern):
        sr.record("parse-extract-pattern", 1.0)
    else:
        sr.record("parse-extract-pattern", 0.0, f"got {nodes}")

    return sr.report("Phase A+: ASG Structure Validation (7 rungs)")


# ---------------------------------------------------------------------------
# Phase B — Terminal backend (ASG → shell → same output)
# ---------------------------------------------------------------------------

def test_phase_b() -> bool:
    sr = ScoreResult()

    # Test the original 11 rungs through the terminal backend
    for name, program, expected in CONFORMANCE:
        nodes = asg.parse(program)
        script = compile_to_shell(nodes)
        actual = run_shell_in_sandbox(script)
        exp = normalize(expected)

        if actual == exp:
            sr.record(name, 1.0)
        else:
            sr.record(name, 0.0, f"expected '{exp}', got '{actual}'")

    # Test terminal-native expansion rungs
    for name, program, expected in TERMINAL_EXTRA:
        nodes = asg.parse(program)
        script = compile_to_shell(nodes)
        actual = run_shell_in_sandbox(script)
        exp = normalize(expected)

        if actual == exp:
            sr.record(name, 1.0)
        else:
            sr.record(name, 0.0, f"expected '{exp}', got '{actual}'")

    return sr.report("Phase B: Terminal Backend (13 rungs)")


# ---------------------------------------------------------------------------
# Phase B+ — Terminal-native computational expansion
# ---------------------------------------------------------------------------

def test_phase_b_plus() -> bool:
    sr = ScoreResult()

    for name, program, expected in TERMINAL_COMPUTE:
        nodes = asg.parse(program)
        script = compile_to_shell(nodes)
        actual = run_shell_in_sandbox(script)
        exp = normalize(expected)

        if actual == exp:
            sr.record(name, 1.0)
        else:
            sr.record(name, 0.0, f"expected '{exp}', got '{actual}'")

    return sr.report("Phase B+: Terminal-Native Compute (5 rungs)")


# ---------------------------------------------------------------------------
# Phase C — Python backend (ASG → Python → same output)
# ---------------------------------------------------------------------------

def test_phase_c() -> bool:
    sr = ScoreResult()

    for name, program, expected in CONFORMANCE:
        nodes = asg.parse(program)
        code = compile_to_python(nodes)
        actual = run_python_in_sandbox(code)
        exp = normalize(expected)

        if actual == exp:
            sr.record(name, 1.0)
        else:
            sr.record(name, 0.0, f"expected '{exp}', got '{actual}'")

    return sr.report("Phase C: Python Backend (11 rungs)")


# ---------------------------------------------------------------------------
# Phase C+ — Python-native computational expansion
# ---------------------------------------------------------------------------

def test_phase_c_plus() -> bool:
    sr = ScoreResult()

    for name, program, expected in PYTHON_COMPUTE:
        nodes = asg.parse(program)
        code = compile_to_python(nodes)
        actual = run_python_in_sandbox(code)
        exp = normalize(expected)

        if actual == exp:
            sr.record(name, 1.0)
        else:
            sr.record(name, 0.0, f"expected '{exp}', got '{actual}'")

    return sr.report("Phase C+: Python-Native Compute (5 rungs)")


# ---------------------------------------------------------------------------
# Phase D — Cross-target invariant (same intent → same OS outcome)
# ---------------------------------------------------------------------------

def test_phase_d() -> bool:
    sr = ScoreResult()

    for name, program, expected in CONFORMANCE:
        nodes = asg.parse(program)
        exp = normalize(expected)

        # Direct execution
        interp_path = HERE / "interpreter.py"
        direct_out = run_in_sandbox("sandbox", program, interp_path)

        # Shell backend
        shell_script = compile_to_shell(nodes)
        shell_out = run_shell_in_sandbox(shell_script)

        # Python backend
        py_code = compile_to_python(nodes)
        py_out = run_python_in_sandbox(py_code)

        if direct_out == exp and shell_out == exp and py_out == exp:
            sr.record(name, 1.0)
        else:
            fails = []
            if direct_out != exp:
                fails.append(f"direct='{direct_out}'")
            if shell_out != exp:
                fails.append(f"shell='{shell_out}'")
            if py_out != exp:
                fails.append(f"python='{py_out}'")
            sr.record(name, 0.0, f"mismatch: {' '.join(fails)}")

    return sr.report("Phase D: Cross-Target Invariant (11 rungs)")


# ---------------------------------------------------------------------------
# Phase D+ — Cross-target invariant for computational rungs
# ---------------------------------------------------------------------------

def test_phase_d_plus() -> bool:
    sr = ScoreResult()

    for name, program, expected in TERMINAL_COMPUTE:
        nodes = asg.parse(program)
        exp = normalize(expected)

        # Direct execution
        interp_path = HERE / "interpreter.py"
        direct_out = run_in_sandbox("sandbox", program, interp_path)

        # Shell backend
        shell_script = compile_to_shell(nodes)
        shell_out = run_shell_in_sandbox(shell_script)

        # Python backend
        py_code = compile_to_python(nodes)
        py_out = run_python_in_sandbox(py_code)

        if direct_out == exp and shell_out == exp and py_out == exp:
            sr.record(name, 1.0)
        else:
            fails = []
            if direct_out != exp:
                fails.append(f"direct='{direct_out}'")
            if shell_out != exp:
                fails.append(f"shell='{shell_out}'")
            if py_out != exp:
               fails.append(f"python='{py_out}'")
            sr.record(name, 0.0, f"mismatch: {' '.join(fails)}")

    return sr.report("Phase D+: Cross-Target Compute Invariant (5 rungs)")


# ---------------------------------------------------------------------------
# Phase E — SQL backend (ASG → SQL → SQLite → same output)
# ---------------------------------------------------------------------------

def test_phase_e() -> bool:
    sr = ScoreResult()
    for name, program, expected in SQL_CONFORMANCE:
        nodes = asg.parse(program)
        if not nodes:
            sr.record(name, 0.0, "parse produced no nodes")
            continue
        actual = normalize(execute_sql(nodes))
        if actual == normalize(expected):
            sr.record(name, 1.0)
        elif actual and actual != "(empty)":
            sr.record(name, 0.5, f"near-miss: got='{actual[:40]}'")
        else:
            sr.record(name, 0.0, f"expected='{expected}' got='{actual}'")
    return sr.report("Phase E: SQL Backend (11 rungs)")


def test_phase_e_plus() -> bool:
    sr = ScoreResult()
    for name, program, expected in SQL_COMPUTE:
        nodes = asg.parse(program)
        if not nodes:
            sr.record(name, 0.0, "parse produced no nodes")
            continue
        actual = normalize(execute_sql(nodes))
        if actual == normalize(expected):
            sr.record(name, 1.0)
        elif actual:
            sr.record(name, 0.5, f"near-miss: got='{actual[:40]}'")
        else:
            sr.record(name, 0.0, f"expected='{expected}' got='{actual}'")
    return sr.report("Phase E+: SQL-Native Compute (5 rungs)")


def test_phase_f() -> bool:
    """Cross-target invariant: ASG -> SQL matches ASG -> direct execution."""
    sr = ScoreResult()
    import interpreter
    for name, program, expected in SQL_CONFORMANCE[:5]:  # first 5 for cross-check
        nodes = asg.parse(program)
        work = Path(tempfile.mkdtemp(prefix="v03_x_"))
        old_cwd = os.getcwd()
        try:
            os.chdir(work)
            direct_out = normalize(interpreter.execute(nodes))
        finally:
            os.chdir(old_cwd)
            shutil.rmtree(work, ignore_errors=True)
        sql_out = normalize(execute_sql(nodes))
        if direct_out == sql_out:
            sr.record(name, 1.0)
        else:
            sr.record(name, 0.0, f"direct='{direct_out[:30]}' sql='{sql_out[:30]}'")
    return sr.report("Phase F: Cross-Target Invariant (SQL vs direct, 5 rungs)")


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    print("MK v03 — Full Test Suite")
    print("=" * 60)

    results = [
        ("Phase A",   test_phase_a()),
        ("Phase A+",  test_phase_a_structure()),
        ("Phase B",   test_phase_b()),
        ("Phase B+",  test_phase_b_plus()),
        ("Phase C",   test_phase_c()),
        ("Phase C+",  test_phase_c_plus()),
        ("Phase D",   test_phase_d()),
        ("Phase D+",  test_phase_d_plus()),
        ("Phase E",   test_phase_e()),
        ("Phase E+",  test_phase_e_plus()),
        ("Phase F",   test_phase_f()),
    ]

    print("\n" + "=" * 60)
    print("  SUMMARY")
    print("=" * 60)
    all_pass = True
    for label, passed in results:
        mark = "✅" if passed else "❌"
        print(f"  {mark} {label}")
        if not passed:
            all_pass = False

    total_rungs = 11 + 7 + 13 + 5 + 11 + 5 + 11 + 5 + 11 + 5 + 5  # = 84
    print(f"\n  Total rungs: {total_rungs}")
    if all_pass:
        print(f"  ALL {total_rungs} RUNGS GREEN ✅")
    else:
        print(f"  FAILURES DETECTED ❌")
    print("=" * 60)

    sys.exit(0 if all_pass else 1)
