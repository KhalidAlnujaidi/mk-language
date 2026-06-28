#!/usr/bin/env python3
"""Test text transformation nodes — ReplaceText, TransformCase, UniqueLines, ReverseLines.

Covers: ASG parse, direct execution, all 4 backends, cross-target invariant.
Run: python3 test_transform.py
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
from interpreter import execute, run
from terminal_backend import compile_to_shell
from python_backend import compile_to_python
from sql_backend import compile_to_sql, execute_sql

passed = 0
failed = 0
results = []


def run_in_sandbox(fn):
    work = Path(tempfile.mkdtemp(prefix="txfm_test_"))
    old = os.getcwd()
    try:
        os.chdir(str(work))
        return fn()
    finally:
        os.chdir(old)
        shutil.rmtree(work, ignore_errors=True)


def normalize(s: str) -> str:
    return " ".join(s.split())


def test(name, cond, detail=""):
    global passed, failed
    if cond:
        passed += 1
        results.append(f"  ✅ {name}")
    else:
        failed += 1
        results.append(f"  ❌ {name}" + (f" — {detail}" if detail else ""))


def run_shell_in_sandbox(script):
    work = Path(tempfile.mkdtemp(prefix="txfm_sh_"))
    try:
        r = subprocess.run(["sh"], input=script, capture_output=True, text=True, cwd=str(work), timeout=10)
        return normalize(r.stdout.strip())
    finally:
        shutil.rmtree(work, ignore_errors=True)


def run_python_in_sandbox(code):
    work = Path(tempfile.mkdtemp(prefix="txfm_py_"))
    try:
        r = subprocess.run([PYTHON, "-c", code], capture_output=True, text=True, cwd=str(work), timeout=10)
        return normalize(r.stdout.strip())
    finally:
        shutil.rmtree(work, ignore_errors=True)


# =========================================================================
# Phase TX1: ASG Parsing
# =========================================================================

def phase_tx1():
    results.append("\nPhase TX1: Text Transform — ASG Parsing")

    n = asg.parse_line('replace "foo" with "bar" in data.txt')
    test("parse ReplaceText",
         isinstance(n, asg.ReplaceText) and n.old == "foo" and n.new == "bar" and n.name == "data.txt",
         str(n))

    n = asg.parse_line("uppercase data.txt")
    test("parse TransformCase upper",
         isinstance(n, asg.TransformCase) and n.mode == "upper" and n.name == "data.txt",
         str(n))

    n = asg.parse_line("lowercase data.txt")
    test("parse TransformCase lower",
         isinstance(n, asg.TransformCase) and n.mode == "lower",
         str(n))

    n = asg.parse_line("titlecase data.txt")
    test("parse TransformCase title",
         isinstance(n, asg.TransformCase) and n.mode == "title",
         str(n))

    n = asg.parse_line("unique lines in data.txt")
    test("parse UniqueLines",
         isinstance(n, asg.UniqueLines) and n.name == "data.txt",
         str(n))

    n = asg.parse_line("reverse lines in data.txt")
    test("parse ReverseLines",
         isinstance(n, asg.ReverseLines) and n.name == "data.txt",
         str(n))


# =========================================================================
# Phase TX2: Direct Execution
# =========================================================================

def phase_tx2():
    results.append("\nPhase TX2: Text Transform — Direct Execution")

    def _exec(source):
        return run_in_sandbox(lambda: normalize(execute(asg.parse(source)).strip()))

    # replace
    result = _exec(
        'create file t.txt with content "hello world"\n'
        'replace "world" with "there" in t.txt')
    test("exec ReplaceText", result == "hello there", result)

    # replace multi-line
    result = _exec(
        'create file m.txt with content "foo bar"\n'
        'append "foo baz" to m.txt\n'
        'replace "foo" with "qux" in m.txt')
    test("exec ReplaceText multiline", result == "qux bar qux baz", result)

    # uppercase
    result = _exec(
        'create file u.txt with content "hello world"\n'
        'uppercase u.txt')
    test("exec TransformCase upper", result == "HELLO WORLD", result)

    # lowercase
    result = _exec(
        'create file l.txt with content "HELLO WORLD"\n'
        'lowercase l.txt')
    test("exec TransformCase lower", result == "hello world", result)

    # titlecase
    result = _exec(
        'create file tc.txt with content "hello world"\n'
        'titlecase tc.txt')
    test("exec TransformCase title", result == "Hello World", result)

    # unique lines
    result = _exec(
        'create file d.txt with content "apple"\n'
        'append "banana" to d.txt\n'
        'append "apple" to d.txt\n'
        'append "cherry" to d.txt\n'
        'append "banana" to d.txt\n'
        'unique lines in d.txt')
    test("exec UniqueLines", result == "apple banana cherry", result)

    # reverse lines
    result = _exec(
        'create file r.txt with content "first"\n'
        'append "second" to r.txt\n'
        'append "third" to r.txt\n'
        'reverse lines in r.txt')
    test("exec ReverseLines", result == "third second first", result)

    # missing file → empty
    result = _exec('replace "a" with "b" in nonexistent.txt')
    test("exec ReplaceText missing file", result == "", result)

    result = _exec('uppercase nonexistent.txt')
    test("exec TransformCase missing file", result == "", result)


# =========================================================================
# Phase TX3: Shell Backend
# =========================================================================

def phase_tx3():
    results.append("\nPhase TX3: Text Transform — Shell Backend")

    def _shell(source):
        nodes = asg.parse(source)
        script = compile_to_shell(nodes)
        return run_shell_in_sandbox(script)

    result = _shell(
        'create file t.txt with content "hello world"\n'
        'replace "world" with "there" in t.txt')
    test("shell ReplaceText", result == "hello there", result)

    result = _shell(
        'create file u.txt with content "hello world"\n'
        'uppercase u.txt')
    test("shell TransformCase upper", result == "HELLO WORLD", result)

    result = _shell(
        'create file l.txt with content "HELLO WORLD"\n'
        'lowercase l.txt')
    test("shell TransformCase lower", result == "hello world", result)

    result = _shell(
        'create file d.txt with content "apple"\n'
        'append "banana" to d.txt\n'
        'append "apple" to d.txt\n'
        'append "cherry" to d.txt\n'
        'unique lines in d.txt')
    test("shell UniqueLines", result == "apple banana cherry", result)

    result = _shell(
        'create file r.txt with content "first"\n'
        'append "second" to r.txt\n'
        'append "third" to r.txt\n'
        'reverse lines in r.txt')
    test("shell ReverseLines", result == "third second first", result)


# =========================================================================
# Phase TX4: Python Backend
# =========================================================================

def phase_tx4():
    results.append("\nPhase TX4: Text Transform — Python Backend")

    def _python(source):
        nodes = asg.parse(source)
        code = compile_to_python(nodes)
        return run_python_in_sandbox(code)

    result = _python(
        'create file t.txt with content "hello world"\n'
        'replace "world" with "there" in t.txt')
    test("python ReplaceText", result == "hello there", result)

    result = _python(
        'create file u.txt with content "hello world"\n'
        'uppercase u.txt')
    test("python TransformCase upper", result == "HELLO WORLD", result)

    result = _python(
        'create file l.txt with content "HELLO WORLD"\n'
        'lowercase l.txt')
    test("python TransformCase lower", result == "hello world", result)

    result = _python(
        'create file tc.txt with content "hello world"\n'
        'titlecase tc.txt')
    test("python TransformCase title", result == "Hello World", result)

    result = _python(
        'create file d.txt with content "apple"\n'
        'append "banana" to d.txt\n'
        'append "apple" to d.txt\n'
        'append "cherry" to d.txt\n'
        'unique lines in d.txt')
    test("python UniqueLines", result == "apple banana cherry", result)

    result = _python(
        'create file r.txt with content "first"\n'
        'append "second" to r.txt\n'
        'append "third" to r.txt\n'
        'reverse lines in r.txt')
    test("python ReverseLines", result == "third second first", result)


# =========================================================================
# Phase TX5: SQL Backend
# =========================================================================

def phase_tx5():
    results.append("\nPhase TX5: Text Transform — SQL Backend")

    def _sql(source):
        nodes = asg.parse(source)
        return run_in_sandbox(lambda: normalize(execute_sql(nodes).strip()))

    result = _sql(
        'create file t.txt with content "hello world"\n'
        'replace "world" with "there" in t.txt')
    test("sql ReplaceText", result == "hello there", result)

    result = _sql(
        'create file u.txt with content "hello world"\n'
        'uppercase u.txt')
    test("sql TransformCase upper", result == "HELLO WORLD", result)

    result = _sql(
        'create file l.txt with content "HELLO WORLD"\n'
        'lowercase l.txt')
    test("sql TransformCase lower", result == "hello world", result)

    result = _sql(
        'create file d.txt with content "apple"\n'
        'append "banana" to d.txt\n'
        'append "apple" to d.txt\n'
        'append "cherry" to d.txt\n'
        'unique lines in d.txt')
    test("sql UniqueLines", result == "apple banana cherry", result)

    result = _sql(
        'create file r.txt with content "first"\n'
        'append "second" to r.txt\n'
        'append "third" to r.txt\n'
        'reverse lines in r.txt')
    test("sql ReverseLines", result == "third second first", result)


# =========================================================================
# Phase TX6: Cross-Target Invariant
# =========================================================================

def phase_tx6():
    results.append("\nPhase TX6: Text Transform — Cross-Target Invariant")

    programs = [
        ("replace",
         'create file t.txt with content "hello world"\n'
         'replace "world" with "there" in t.txt'),
        ("uppercase",
         'create file u.txt with content "hello world"\n'
         'uppercase u.txt'),
        ("lowercase",
         'create file l.txt with content "HELLO WORLD"\n'
         'lowercase l.txt'),
        ("unique",
         'create file d.txt with content "apple"\n'
         'append "banana" to d.txt\n'
         'append "apple" to d.txt\n'
         'append "cherry" to d.txt\n'
         'unique lines in d.txt'),
        ("reverse",
         'create file r.txt with content "first"\n'
         'append "second" to r.txt\n'
         'append "third" to r.txt\n'
         'reverse lines in r.txt'),
    ]

    for name, source in programs:
        nodes = asg.parse(source)

        direct = run_in_sandbox(lambda: normalize(execute(nodes).strip()))
        shell_out = run_shell_in_sandbox(compile_to_shell(nodes))
        py_out = run_python_in_sandbox(compile_to_python(nodes))

        test(f"cross-target {name} (direct==shell)",
             direct == shell_out, f"direct='{direct}' shell='{shell_out}'")
        test(f"cross-target {name} (direct==python)",
             direct == py_out, f"direct='{direct}' py='{py_out}'")


# =========================================================================
# Phase TX7: Iteration Integration (transform inside ForEachFile)
# =========================================================================

def phase_tx7():
    results.append("\nPhase TX7: Text Transform — Iteration Integration")

    def _exec(source):
        return run_in_sandbox(lambda: normalize(execute(asg.parse(source)).strip()))

    # This tests that transform nodes work with {file} placeholder substitution
    # in ForEachFile bodies.
    # Setup: create two files, then uppercase each via for-each
    result = _exec(
        'create file a.txt with content "hello"\n'
        'create file b.txt with content "world"\n')
    # We can't easily test ForEachFile with transforms through the planner yet,
    # but we can test the direct ASG path
    nodes = asg.parse(
        'create file a.txt with content "hello"\n'
        'create file b.txt with content "world"')
    # Build a ForEachFile with an uppercase body
    body = (asg.TransformCase(name="{file}", mode="upper"),)
    fe = asg.ForEachFile(glob_pattern="*.txt", body_template=body, placeholder="{file}")
    nodes = list(nodes) + [fe]
    result = run_in_sandbox(lambda: normalize(execute(nodes).strip()))
    test("forEach uppercase *.txt", result == "HELLO WORLD", result)


# =========================================================================
# Phase TX8: Planner Rules
# =========================================================================

def phase_tx8():
    results.append("\nPhase TX8: Text Transform — Planner Rules")

    # These planner rules don't exist yet — we'll add them after tests pass
    # For now, test passthrough: these should pass through to the parser unchanged
    from planner import Planner
    planner = Planner(use_llm=False)

    for intent in [
        'replace "foo" with "bar" in data.txt',
        "uppercase data.txt",
        "lowercase data.txt",
        "unique lines in data.txt",
        "reverse lines in data.txt",
    ]:
        plan = planner.plan(intent)
        test(f"passthrough: {intent}",
             len(plan.steps) == 1 and plan.steps[0] == intent,
             str(plan))


# =========================================================================
# Main
# =========================================================================

def main():
    print("Text Transformation Tests")
    print("=" * 60)

    phase_tx1()
    phase_tx2()
    phase_tx3()
    phase_tx4()
    phase_tx5()
    phase_tx6()
    phase_tx7()
    phase_tx8()

    print()
    for r in results:
        print(r)

    total = passed + failed
    print(f"\n{'=' * 60}")
    if failed == 0:
        print(f"  ALL {total} RUNGS GREEN ✅")
    else:
        print(f"  {passed}/{total} passed, {failed} FAILED")
    print(f"{'=' * 60}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
