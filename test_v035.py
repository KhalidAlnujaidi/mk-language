#!/usr/bin/env python3
"""Test suite for v03.5: WriteFile, ArithmeticExpr, FileExists.

Tests:
  Phase A: Parse — verify NL → ASG node mapping
  Phase B: Execute — verify direct interpreter execution
  Phase C: Shell backend — verify shell compilation
  Phase D: Python backend — verify Python compilation
  Phase E: SQL backend — verify SQL compilation
  Phase F: Cross-target invariants — same ASG → same output across backends
  Phase G: Integration — variable binding + arithmetic, WriteFile overwrite
"""

import os
import sys
import tempfile
import subprocess

sys.path.insert(0, os.path.dirname(__file__))

import asg
from interpreter import execute
from terminal_backend import compile_to_shell
from python_backend import compile_to_python
from sql_backend import compile_to_sql

passed = 0
failed = 0


def test(name, condition, detail=""):
    global passed, failed
    if condition:
        passed += 1
        print(f"  ✅ {name}")
    else:
        failed += 1
        print(f"  ❌ {name} — {detail}")


def _make_multiline_file(name, lines):
    """Create a file with actual newlines using interpreter."""
    execute(asg.parse(f'create file {name} with content "{lines[0]}"'))
    for line in lines[1:]:
        execute(asg.parse(f'append "{line}" to {name}'))


# ---------------------------------------------------------------------------
# Phase A: Parse
# ---------------------------------------------------------------------------

print("\n=== Phase A: Parse ===")

n = asg.parse_line('write "hello" to file.txt')
test("parse write", isinstance(n, asg.WriteFile) and n.name == "file.txt" and n.content == "hello",
     f"got {n}")

n = asg.parse_line('overwrite file.txt with "new"')
test("parse overwrite", isinstance(n, asg.WriteFile) and n.name == "file.txt" and n.content == "new",
     f"got {n}")

n = asg.parse_line('compute 2 + 3')
test("parse compute", isinstance(n, asg.ArithmeticExpr) and n.expr == "2 + 3",
     f"got {n}")

n = asg.parse_line('compute (10 - 4) * 2')
test("parse compute parens", isinstance(n, asg.ArithmeticExpr) and n.expr == "(10 - 4) * 2",
     f"got {n}")

n = asg.parse_line('add $A and $B')
test("parse add vars", isinstance(n, asg.ArithmeticExpr) and "{A}" in n.expr and "{B}" in n.expr,
     f"got {n}")

n = asg.parse_line('subtract $X from $Y')
test("parse subtract vars", isinstance(n, asg.ArithmeticExpr) and "{Y}" in n.expr and "{X}" in n.expr,
     f"got {n}")

n = asg.parse_line('exists file.txt')
test("parse exists", isinstance(n, asg.FileExists) and n.name == "file.txt",
     f"got {n}")

n = asg.parse_line('does file.txt exist')
test("parse does exist", isinstance(n, asg.FileExists) and n.name == "file.txt",
     f"got {n}")


# ---------------------------------------------------------------------------
# Phase B: Execute
# ---------------------------------------------------------------------------

print("\n=== Phase B: Execute ===")

with tempfile.TemporaryDirectory() as tmpdir:
    old_cwd = os.getcwd()
    os.chdir(tmpdir)
    try:
        # WriteFile: create new
        execute(asg.parse('write "hello world" to new.txt'))
        result = execute(asg.parse('read file new.txt'))
        test("exec write new file", result.strip() == "hello world", f"got {result!r}")

        # WriteFile: overwrite existing
        execute(asg.parse('write "replaced" to new.txt'))
        result = execute(asg.parse('read file new.txt'))
        test("exec write overwrite", result.strip() == "replaced", f"got {result!r}")

        # WriteFile does NOT refuse like CreateFile
        execute(asg.parse('create file orig.txt with content "original"'))
        execute(asg.parse('write "changed" to orig.txt'))
        result = execute(asg.parse('read file orig.txt'))
        test("exec write does not refuse", result.strip() == "changed", f"got {result!r}")

        # ArithmeticExpr: basic ops
        test("exec add", execute(asg.parse('compute 2 + 3')).strip() == "5")
        test("exec subtract", execute(asg.parse('compute 10 - 4')).strip() == "6")
        test("exec multiply", execute(asg.parse('compute 3 * 7')).strip() == "21")
        test("exec divide (floor)", execute(asg.parse('compute 20 / 6')).strip() == "3")
        test("exec parens", execute(asg.parse('compute (2 + 3) * 4')).strip() == "20")
        test("exec unary minus", execute(asg.parse('compute -5 + 10')).strip() == "5")
        test("exec chained multiply", execute(asg.parse('compute 2 * 2 * 2')).strip() == "8")
        test("exec modulo", execute(asg.parse('compute 100 % 7')).strip() == "2")
        test("exec power", execute(asg.parse('compute 2 ** 4')).strip() == "16")

        # FileExists
        execute(asg.parse('create file present.txt with content "data"'))
        test("exec exists yes", execute(asg.parse('exists present.txt')).strip() == "yes")
        test("exec exists no", execute(asg.parse('exists absent.txt')).strip() == "no")
        test("exec does exist", execute(asg.parse('does present.txt exist')).strip() == "yes")

        # Variable + Arithmetic — use real multiline file
        _make_multiline_file('data.txt', ['line1', 'line2', 'line3'])
        result = execute(asg.parse('set N = count lines in data.txt\ncompute {N} * 10'))
        test("exec var+arith", result.strip() == "30", f"got {result!r}")

        result = execute(asg.parse('set N = count lines in data.txt\ncompute {N} + 100'))
        test("exec var+arith2", result.strip() == "103", f"got {result!r}")

        # WriteFile with variable substitution (must be same execute call for var scope)
        result = execute(asg.parse(
            'set N = count lines in data.txt\n'
            'write "Has {N} lines" to result.txt\n'
            'read file result.txt'
        ))
        test("exec write with var", result.strip() == "Has 3 lines", f"got {result!r}")

    finally:
        os.chdir(old_cwd)

print("\n=== Phase C: Shell Backend ===")

nodes = asg.parse('write "hello" to out.txt')
shell = compile_to_shell(nodes)
test("shell write", 'printf' in shell and 'out.txt' in shell and '>' in shell, shell)

nodes = asg.parse('compute 2 + 3')
shell = compile_to_shell(nodes)
test("shell compute", '$((' in shell and '2 + 3' in shell, shell)

nodes = asg.parse('exists data.txt')
shell = compile_to_shell(nodes)
test("shell exists", '[ -f' in shell and ('yes' in shell or 'no' in shell), shell)

with tempfile.TemporaryDirectory() as tmpdir:
    old_cwd = os.getcwd()
    os.chdir(tmpdir)
    try:
        shell_code = compile_to_shell(asg.parse('write "test" to sh_test.txt'))
        with open('_run.sh', 'w') as f:
            f.write(shell_code)
        subprocess.run(['sh', '_run.sh'], capture_output=True)
        test("shell write exec", os.path.exists('sh_test.txt'))
        if os.path.exists('sh_test.txt'):
            with open('sh_test.txt') as f:
                content = f.read()
            test("shell write content", content.strip() == "test", f"got {content!r}")
    finally:
        os.chdir(old_cwd)


# ---------------------------------------------------------------------------
# Phase D: Python backend compilation
# ---------------------------------------------------------------------------

print("\n=== Phase D: Python Backend ===")

nodes = asg.parse('write "hello" to out.txt')
py = compile_to_python(nodes)
test("python write", "open(" in py and "'w'" in py, py[:200])

nodes = asg.parse('compute 2 + 3')
py = compile_to_python(nodes)
test("python compute", "ast" in py, py[:200])

nodes = asg.parse('exists data.txt')
py = compile_to_python(nodes)
test("python exists", "os.path.exists" in py, py[:200])

with tempfile.TemporaryDirectory() as tmpdir:
    old_cwd = os.getcwd()
    os.chdir(tmpdir)
    try:
        py_code = compile_to_python(asg.parse('write "pytest" to py_out.txt'))
        with open('_run.py', 'w') as f:
            f.write(py_code)
        result = subprocess.run([sys.executable, '_run.py'], capture_output=True, text=True)
        test("python write exec", os.path.exists('py_out.txt'), f"stderr={result.stderr[:200]}")
        if os.path.exists('py_out.txt'):
            with open('py_out.txt') as f:
                content = f.read()
            test("python write content", content.strip() == "pytest", f"got {content!r}")
    finally:
        os.chdir(old_cwd)


# ---------------------------------------------------------------------------
# Phase E: SQL backend compilation
# ---------------------------------------------------------------------------

print("\n=== Phase E: SQL Backend ===")

nodes = asg.parse('write "hello" to out.txt')
sql = compile_to_sql(nodes)
test("sql write", "DROP TABLE" in sql and "CREATE TABLE" in sql, sql[:200])

nodes = asg.parse('compute 2 + 3')
sql = compile_to_sql(nodes)
test("sql compute", "SELECT" in sql and "2 + 3" in sql, sql[:200])

nodes = asg.parse('exists data.txt')
sql = compile_to_sql(nodes)
test("sql exists", "SELECT" in sql and "sqlite_master" in sql, sql[:200])


# ---------------------------------------------------------------------------
# Phase F: Cross-target invariants
# ---------------------------------------------------------------------------

print("\n=== Phase F: Cross-Target Invariants ===")

for intent in ['write "x" to f.txt', 'compute 1 + 1', 'exists f.txt']:
    nodes = asg.parse(intent)
    assert len(nodes) == 1, f"Expected 1 node for {intent!r}"
    s = compile_to_shell(nodes)
    p = compile_to_python(nodes)
    q = compile_to_sql(nodes)
    test(f"cross-target compiles ({intent})",
         len(s) > 0 and len(p) > 0 and len(q) > 0,
         f"shell={len(s)} py={len(p)} sql={len(q)}")


# ---------------------------------------------------------------------------
# Phase G: Integration
# ---------------------------------------------------------------------------

print("\n=== Phase G: Integration ===")

with tempfile.TemporaryDirectory() as tmpdir:
    old_cwd = os.getcwd()
    os.chdir(tmpdir)
    try:
        # Create multi-line file with numbers
        _make_multiline_file('nums.txt', ['1', '2', '3', '4', '5'])

        # Full pipeline: count → sum → compute avg → write report
        result = execute(asg.parse(
            'set COUNT = count lines in nums.txt\n'
            'set SUM = sum numbers in nums.txt\n'
            'set AVG = compute {SUM} / {COUNT}\n'
            'write "Count: {COUNT}, Sum: {SUM}, Avg: {AVG}" to report.txt\n'
            'read file report.txt'
        ))
        expected = "Count: 5, Sum: 15, Avg: 3"
        test("integration pipeline", result.strip() == expected, f"got {result!r}, expected {expected!r}")

        # WriteFile + IfVar
        result = execute(asg.parse(
            'set N = count lines in nums.txt\n'
            'if $N > 3 then write "big" to class.txt otherwise write "small" to class.txt\n'
            'read file class.txt'
        ))
        test("write+ifvar integration", result.strip() == "big", f"got {result!r}")

        # add $A and $B
        result = execute(asg.parse('set A = compute 5\nset B = compute 3\nadd $A and $B'))
        test("add vars integration", result.strip() == "8", f"got {result!r}")

        # subtract vars
        result = execute(asg.parse('set A = compute 10\nset B = compute 3\nsubtract $B from $A'))
        test("subtract vars integration", result.strip() == "7", f"got {result!r}")

    finally:
        os.chdir(old_cwd)


# ---------------------------------------------------------------------------
# Results
# ---------------------------------------------------------------------------

print(f"\n{'='*60}")
print(f"  v03.5 RESULTS: {passed}/{passed + failed} passed", end="")
if failed == 0:
    print(" — ALL GREEN ✅")
else:
    print(f" — {failed} FAILED ❌")
print(f"{'='*60}")
sys.exit(0 if failed == 0 else 1)
