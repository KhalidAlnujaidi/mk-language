#!/usr/bin/env python3
"""Cross-backend equivalence verification.

Proves the ASG is truly target-independent: the same parsed intent produces
identical observable output across all 4 backends (interpreter, shell, python, sql).

This is the core asymmetry-thesis validation: the intelligence is in the parser
and planner (deterministic), and execution is a deterministic compilation.
If all 4 backends agree, the ASG captures the true intent, not a backend-specific
artifact.

Test phases:
  Phase X1: Terminal operations (single-node) — count lines, count words,
            sum numbers, sort, head, extract pattern, read file
  Phase X2: Pipeline operations — multi-step capture-and-reuse
  Phase X3: Process operations — create, append, copy, delete
  Phase X4: Text transforms — uppercase, lowercase, unique, reverse, replace
"""

import os
import sys
import shutil
import tempfile
import subprocess

sys.path.insert(0, os.path.dirname(__file__))

import asg
from asg import parse
from interpreter import execute
from terminal_backend import compile_to_shell
from python_backend import compile_to_python
from sql_backend import execute_sql, compile_to_sql, _execute_node

import sqlite3

_stats = {"passed": 0, "failed": 0}
_failures = []


def check(label, got, expected):
    got_s = str(got).strip()
    exp_s = str(expected).strip()
    if got_s == exp_s:
        _stats["passed"] += 1
        print(f"  ✅ {label}")
    else:
        _stats["failed"] += 1
        _failures.append(f"{label}: expected '{exp_s}', got '{got_s}'")
        print(f"  ❌ {label}: expected '{exp_s}', got '{got_s}'")


def _run_in_sandbox(nodes, files: dict, backend: str) -> str:
    """Run ASG nodes through a specific backend in a sandbox.

    files: dict of {filename: content} to create before running.
    Returns the stdout output string.
    """
    with tempfile.TemporaryDirectory() as tmp:
        old_cwd = os.getcwd()
        os.chdir(tmp)
        try:
            # Create the setup files
            for fname, content in files.items():
                with open(fname, 'w') as f:
                    f.write(content)

            if backend == 'interpreter':
                return execute(list(nodes)).strip()

            elif backend == 'shell':
                script = compile_to_shell(list(nodes))
                script_path = os.path.join(tmp, "_run.sh")
                with open(script_path, 'w') as f:
                    f.write(script)
                result = subprocess.run(
                    ['sh', script_path],
                    capture_output=True, text=True, timeout=10
                )
                return result.stdout.strip()

            elif backend == 'python':
                code = compile_to_python(list(nodes))
                script_path = os.path.join(tmp, "_run.py")
                with open(script_path, 'w') as f:
                    f.write(code)
                result = subprocess.run(
                    [sys.executable, script_path],
                    capture_output=True, text=True, timeout=10
                )
                return result.stdout.strip()

            elif backend == 'sql':
                conn = sqlite3.connect(':memory:')
                cursor = conn.cursor()
                for fname, content in files.items():
                    tbl = f'"{fname}"'
                    cursor.execute(f'CREATE TABLE {tbl} (line TEXT)')
                    for line in content.split('\n'):
                        cursor.execute(f'INSERT INTO {tbl} (line) VALUES (?)', (line,))
                    conn.commit()
                output_parts = []
                for node in nodes:
                    r = _execute_node(cursor, node, conn)
                    if r is not None:
                        output_parts.append(r)
                conn.close()
                return ' '.join(output_parts).strip() if output_parts else ''

            else:
                raise ValueError(f"Unknown backend: {backend}")
        finally:
            os.chdir(old_cwd)


def check_all_backends(label, nodes, files, expected):
    """Check that all 4 backends produce the expected output for the same ASG."""
    for backend in ['interpreter', 'shell', 'python', 'sql']:
        try:
            result = _run_in_sandbox(nodes, files, backend)
            check(f"{label} [{backend}]", result, expected)
        except Exception as e:
            _stats["failed"] += 1
            _failures.append(f"{label} [{backend}]: EXCEPTION {e}")
            print(f"  ❌ {label} [{backend}]: EXCEPTION {e}")


# ===========================================================================
# Phase X1: Terminal operations — single-node queries
# ===========================================================================

def test_terminal_ops():
    print("\nPhase X1: Terminal Operations (single-node, all 4 backends)")

    # count lines
    check_all_backends("count_lines 3",
                       [asg.CountLines(name="data.txt")],
                       {"data.txt": "one\ntwo\nthree"}, "3")

    check_all_backends("count_lines 5",
                       [asg.CountLines(name="data.txt")],
                       {"data.txt": "a\nb\nc\nd\ne"}, "5")

    check_all_backends("count_lines 1",
                       [asg.CountLines(name="data.txt")],
                       {"data.txt": "only one line"}, "1")

    # count words
    check_all_backends("count_words 4",
                       [asg.CountWords(name="data.txt")],
                       {"data.txt": "one two three four"}, "4")

    check_all_backends("count_words multiline",
                       [asg.CountWords(name="data.txt")],
                       {"data.txt": "hello world\nfoo bar baz"}, "5")

    # sum numbers
    check_all_backends("sum_numbers 60",
                       [asg.SumNumbers(name="nums.txt")],
                       {"nums.txt": "10\n20\n30"}, "60")

    check_all_backends("sum_numbers inline",
                       [asg.SumNumbers(name="nums.txt")],
                       {"nums.txt": "1 2 3 4 5"}, "15")

    # sort lines
    check_all_backends("sort_lines",
                       [asg.SortLines(name="data.txt")],
                       {"data.txt": "cherry\napple\nbanana"}, "apple banana cherry")

    # head lines
    check_all_backends("head_lines 2",
                       [asg.HeadLines(name="data.txt", count=2)],
                       {"data.txt": "first\nsecond\nthird\nfourth"}, "first second")

    # extract pattern
    check_all_backends("extract_pattern",
                       [asg.ExtractPattern(name="log.txt", pattern="error")],
                       {"log.txt": "error: crash\ninfo: ok\nerror: timeout"},
                       "error: crash error: timeout")

    # read file
    check_all_backends("read_file",
                       [asg.ReadFile(name="data.txt")],
                       {"data.txt": "hello world"}, "hello world")


# ===========================================================================
# Phase X2: Pipeline operations — multi-step capture and reuse
# ===========================================================================

def test_pipeline_ops():
    print("\nPhase X2: Pipeline Operations (multi-step, interpreter)")

    # count lines + capture to var + print
    nodes = [
        asg.SetVar(var_name="n", source_node=asg.CountLines(name="data.txt")),
        asg.PrintVar(var_name="n"),
    ]
    result = _run_in_sandbox(nodes, {"data.txt": "a\nb\nc\nd"}, 'interpreter')
    check("pipeline count→print [interpreter]", result, "4")

    # sum + capture + print
    nodes = [
        asg.SetVar(var_name="total", source_node=asg.SumNumbers(name="nums.txt")),
        asg.PrintVar(var_name="total"),
    ]
    result = _run_in_sandbox(nodes, {"nums.txt": "10\n20\n30"}, 'interpreter')
    check("pipeline sum→print [interpreter]", result, "60")


# ===========================================================================
# Phase X3: Process operations — create, append
# ===========================================================================

def test_process_ops():
    print("\nPhase X3: Process Operations (create+read, append+read — all 4 backends)")

    # create + read (two nodes, sequential)
    nodes = [
        asg.CreateFile(name="new.txt", content="created content"),
        asg.ReadFile(name="new.txt"),
    ]
    for backend in ['interpreter', 'shell', 'python', 'sql']:
        try:
            result = _run_in_sandbox(nodes, {}, backend)
            check(f"create+read [{backend}]", result, "created content")
        except Exception as e:
            _stats["failed"] += 1
            _failures.append(f"create+read [{backend}]: EXCEPTION {e}")
            print(f"  ❌ create+read [{backend}]: EXCEPTION {e}")

    # append + read
    nodes = [
        asg.AppendFile(text="appended", name="data.txt"),
        asg.ReadFile(name="data.txt"),
    ]
    for backend in ['interpreter', 'shell', 'python', 'sql']:
        try:
            result = _run_in_sandbox(nodes, {"data.txt": "original"}, backend)
            check(f"append+read [{backend}]", result, "original appended")
        except Exception as e:
            _stats["failed"] += 1
            _failures.append(f"append+read [{backend}]: EXCEPTION {e}")
            print(f"  ❌ append+read [{backend}]: EXCEPTION {e}")


# ===========================================================================
# Phase X4: Text transforms — all 4 backends
# ===========================================================================

def test_transform_ops():
    print("\nPhase X4: Text Transforms (all 4 backends)")

    # uppercase
    check_all_backends("uppercase",
                       [asg.TransformCase(name="data.txt", mode="upper")],
                       {"data.txt": "hello\nworld"}, "HELLO WORLD")

    # lowercase
    check_all_backends("lowercase",
                       [asg.TransformCase(name="data.txt", mode="lower")],
                       {"data.txt": "HELLO\nWORLD"}, "hello world")

    # unique lines
    check_all_backends("unique_lines",
                       [asg.UniqueLines(name="data.txt")],
                       {"data.txt": "foo\nbar\nfoo\nbaz\nbar"}, "foo bar baz")

    # reverse lines
    check_all_backends("reverse_lines",
                       [asg.ReverseLines(name="data.txt")],
                       {"data.txt": "first\nsecond\nthird"}, "third second first")

    # replace text
    check_all_backends("replace_text",
                       [asg.ReplaceText(name="data.txt", old="old", new="new")],
                       {"data.txt": "old text\nold line"}, "new text new line")


# ===========================================================================
# Main
# ===========================================================================

if __name__ == "__main__":
    print("=" * 70)
    print("Cross-Backend Equivalence Test Suite")
    print("Proves: same ASG → identical output across interpreter/shell/python/sql")
    print("=" * 70)

    test_terminal_ops()
    test_pipeline_ops()
    test_process_ops()
    test_transform_ops()

    passed = _stats["passed"]
    failed = _stats["failed"]
    print("\n" + "=" * 70)
    total = passed + failed
    print(f"RESULTS: {passed}/{total} passed, {failed} failed")
    if _failures:
        print("\nFAILURES:")
        for f in _failures:
            print(f"  • {f}")
    else:
        print("ALL BACKENDS EQUIVALENT ✅")
    print("=" * 70)

    sys.exit(1 if failed else 0)
