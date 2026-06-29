#!/usr/bin/env python3
"""Cross-backend pipeline equivalence verification.

Proves that multi-step pipeline ASG nodes (SetVar, PrintVar, WriteFile,
ArithmeticExpr, FileExists) produce IDENTICAL output across all 4 backends:
interpreter, shell, python, sql.

This is the core asymmetry-thesis validation for pipelines: the intelligence
is in the planner (deterministic), and every backend compiles the same ASG
to the same observable output.

Test phases:
  Phase XP1: SetVar + PrintVar pipelines (capture → print)
  Phase XP2: SetVar + ArithmeticExpr pipelines (capture → compute)
  Phase XP3: WriteFile pipelines (write → read back)
  Phase XP4: Standalone nodes (ArithmeticExpr, FileExists)
"""

import os
import sys
import tempfile
import subprocess
import sqlite3

sys.path.insert(0, os.path.dirname(__file__))

import asg
from interpreter import execute
from terminal_backend import compile_to_shell
from python_backend import compile_to_python
from sql_backend import _execute_node as sql_exec_node

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


def _run_in_sandbox(nodes, files, backend):
    """Run ASG nodes through a specific backend in a temp sandbox."""
    with tempfile.TemporaryDirectory() as tmp:
        old_cwd = os.getcwd()
        os.chdir(tmp)
        try:
            for fname, content in files.items():
                with open(fname, 'w') as f:
                    f.write(content)

            if backend == 'interpreter':
                return execute(list(nodes)).strip()

            elif backend == 'shell':
                script = compile_to_shell(list(nodes))
                with open("_run.sh", 'w') as f:
                    f.write(script)
                result = subprocess.run(['sh', '_run.sh'],
                    capture_output=True, text=True, timeout=10)
                return result.stdout.strip()

            elif backend == 'python':
                code = compile_to_python(list(nodes))
                with open("_run.py", 'w') as f:
                    f.write(code)
                result = subprocess.run([sys.executable, '_run.py'],
                    capture_output=True, text=True, timeout=10)
                return result.stdout.strip()

            elif backend == 'sql':
                conn = sqlite3.connect(':memory:')
                cursor = conn.cursor()
                _vars = {}
                for fname, content in files.items():
                    tbl = f'"{fname}"'
                    cursor.execute(f'CREATE TABLE {tbl} (line TEXT)')
                    for line in content.split('\n'):
                        cursor.execute(f'INSERT INTO {tbl} (line) VALUES (?)', (line,))
                    conn.commit()
                output_parts = []
                for node in nodes:
                    r = sql_exec_node(cursor, node, conn, _vars)
                    if r is not None:
                        output_parts.append(r)
                conn.close()
                return ' '.join(output_parts).strip() if output_parts else ''

            else:
                raise ValueError(f"Unknown backend: {backend}")
        finally:
            os.chdir(old_cwd)


def check_all_backends(label, nodes, files, expected):
    """Check that all 4 backends produce the expected output."""
    for backend in ['interpreter', 'shell', 'python', 'sql']:
        try:
            result = _run_in_sandbox(nodes, files, backend)
            check(f"{label} [{backend}]", result, expected)
        except Exception as e:
            _stats["failed"] += 1
            _failures.append(f"{label} [{backend}]: EXCEPTION {e}")
            print(f"  ❌ {label} [{backend}]: EXCEPTION {e}")


# ===========================================================================
# Phase XP1: SetVar + PrintVar pipelines (capture → print)
# ===========================================================================

def test_setvar_printvar():
    print("\nPhase XP1: SetVar + PrintVar (capture → print, all 4 backends)")

    # count lines → print
    check_all_backends("count→print 3",
        [asg.SetVar(var_name="n", source_node=asg.CountLines(name="data.txt")),
         asg.PrintVar(var_name="n")],
        {"data.txt": "one\ntwo\nthree"}, "3")

    check_all_backends("count→print 5",
        [asg.SetVar(var_name="n", source_node=asg.CountLines(name="data.txt")),
         asg.PrintVar(var_name="n")],
        {"data.txt": "a\nb\nc\nd\ne"}, "5")

    # count words → print
    check_all_backends("words→print 4",
        [asg.SetVar(var_name="n", source_node=asg.CountWords(name="data.txt")),
         asg.PrintVar(var_name="n")],
        {"data.txt": "one two three four"}, "4")

    # sum numbers → print
    check_all_backends("sum→print 60",
        [asg.SetVar(var_name="total", source_node=asg.SumNumbers(name="nums.txt")),
         asg.PrintVar(var_name="total")],
        {"nums.txt": "10\n20\n30"}, "60")

    # sum numbers → print (inline)
    check_all_backends("sum→print 15",
        [asg.SetVar(var_name="total", source_node=asg.SumNumbers(name="nums.txt")),
         asg.PrintVar(var_name="total")],
        {"nums.txt": "1 2 3 4 5"}, "15")

    # read file → print
    check_all_backends("read→print",
        [asg.SetVar(var_name="content", source_node=asg.ReadFile(name="data.txt")),
         asg.PrintVar(var_name="content")],
        {"data.txt": "hello world"}, "hello world")

    # sort → print
    check_all_backends("sort→print",
        [asg.SetVar(var_name="sorted", source_node=asg.SortLines(name="data.txt")),
         asg.PrintVar(var_name="sorted")],
        {"data.txt": "cherry\napple\nbanana"}, "apple banana cherry")

    # extract → print
    check_all_backends("extract→print",
        [asg.SetVar(var_name="errors", source_node=asg.ExtractPattern(name="log.txt", pattern="error")),
         asg.PrintVar(var_name="errors")],
        {"log.txt": "error: crash\ninfo: ok\nerror: timeout"},
        "error: crash error: timeout")


# ===========================================================================
# Phase XP2: SetVar + ArithmeticExpr pipelines (capture → compute)
# ===========================================================================

def test_setvar_arithmetic():
    print("\nPhase XP2: SetVar + ArithmeticExpr (capture → compute)")

    # count lines → multiply
    check_all_backends("count→mul 12",
        [asg.SetVar(var_name="n", source_node=asg.CountLines(name="data.txt")),
         asg.ArithmeticExpr(expr="{n} * 3")],
        {"data.txt": "a\nb\nc\nd"}, "12")

    # count lines → add
    check_all_backends("count→add 102",
        [asg.SetVar(var_name="n", source_node=asg.CountLines(name="data.txt")),
         asg.ArithmeticExpr(expr="{n} + 100")],
        {"data.txt": "x\ny"}, "102")

    # sum → multiply
    check_all_backends("sum→mul 120",
        [asg.SetVar(var_name="total", source_node=asg.SumNumbers(name="nums.txt")),
         asg.ArithmeticExpr(expr="{total} * 2")],
        {"nums.txt": "10\n20\n30"}, "120")

    # sum → subtract
    check_all_backends("sum→sub 50",
        [asg.SetVar(var_name="total", source_node=asg.SumNumbers(name="nums.txt")),
         asg.ArithmeticExpr(expr="{total} - 10")],
        {"nums.txt": "20\n30\n10"}, "50")


# ===========================================================================
# Phase XP3: WriteFile pipelines (write → read back)
# ===========================================================================

def test_writefile_pipeline():
    print("\nPhase XP3: WriteFile pipeline (capture → write → read)")

    # count → write → read back
    # This needs multi-step: set var, write to file, then read the file
    check_all_backends("count→write→read",
        [asg.SetVar(var_name="n", source_node=asg.CountLines(name="data.txt")),
         asg.WriteFile(name="result.txt", content="{n}"),
         asg.ReadFile(name="result.txt")],
        {"data.txt": "one\ntwo\nthree\nfour"}, "4")

    # sum → write → read back
    check_all_backends("sum→write→read",
        [asg.SetVar(var_name="total", source_node=asg.SumNumbers(name="nums.txt")),
         asg.WriteFile(name="total.txt", content="{total}"),
         asg.ReadFile(name="total.txt")],
        {"nums.txt": "10\n20\n30"}, "60")


# ===========================================================================
# Phase XP4: Standalone nodes (ArithmeticExpr, FileExists)
# ===========================================================================

def test_standalone_nodes():
    print("\nPhase XP4: Standalone nodes (all 4 backends)")

    # Pure arithmetic
    check_all_backends("arith 5*3",
        [asg.ArithmeticExpr(expr="5 * 3")], {}, "15")

    check_all_backends("arith 10+7",
        [asg.ArithmeticExpr(expr="10 + 7")], {}, "17")

    check_all_backends("arith 20-8",
        [asg.ArithmeticExpr(expr="20 - 8")], {}, "12")

    check_all_backends("arith 100/4",
        [asg.ArithmeticExpr(expr="100 / 4")], {}, "25")

    # FileExists: yes
    check_all_backends("exists yes",
        [asg.FileExists(name="data.txt")],
        {"data.txt": "hello"}, "yes")

    # FileExists: no
    check_all_backends("exists no",
        [asg.FileExists(name="nope.txt")], {}, "no")


# ===========================================================================
# Main
# ===========================================================================

if __name__ == "__main__":
    print("=" * 60)
    print("Cross-Backend Pipeline Equivalence Verification")
    print("Proving: same ASG → identical output across all 4 backends")
    print("=" * 60)

    test_setvar_printvar()
    test_setvar_arithmetic()
    test_writefile_pipeline()
    test_standalone_nodes()

    total = _stats["passed"] + _stats["failed"]
    print(f"\n{'=' * 60}")
    print(f"Results: {_stats['passed']}/{total} passed, {_stats['failed']} failed")
    if _failures:
        print("\nFailures:")
        for f in _failures:
            print(f"  ✗ {f}")
    else:
        print("\n✅ ALL PIPELINE OPERATIONS EQUIVALENT ACROSS 4 BACKENDS")
    print("=" * 60)

    sys.exit(1 if _stats["failed"] else 0)
