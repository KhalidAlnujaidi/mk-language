"""Test suite for v03.4: TailLines, FilterLines, IfVar.

Tests across all 4 backends (interpreter, shell, python, sql) to prove
the ASG remains target-independent with the new nodes.
"""

import os
import sys
import tempfile

import asg
from asg import TailLines, FilterLines, IfVar, SetVar, PrintVar, CreateFile, CountLines, ReadFile
from interpreter import execute
from terminal_backend import compile_to_shell
from python_backend import compile_to_python
from sql_backend import compile_to_sql, execute_sql


def _make_file(tmpdir, name, content):
    """Create a test file in tmpdir."""
    path = os.path.join(tmpdir, name)
    with open(path, 'w') as f:
        f.write(content)
    return path


_passed = 0
_failed = 0
_failures = []


def run_rung(name, fn):
    global _passed, _failed
    try:
        result = fn()
        if result is True or result is None:
            _passed += 1
            print(f"  ✅ {name}")
        else:
            _failed += 1
            _failures.append((name, str(result) if result else "returned False"))
            print(f"  ❌ {name}: {result}")
    except Exception as e:
        _failed += 1
        _failures.append((name, str(e)))
        print(f"  ❌ {name}: {e}")


def _assert_eq(actual, expected, label=""):
    if actual.strip() == expected.strip():
        return True
    return f"{label}expected '{expected}', got '{actual}'"


# --- Phase A: ASG Parsing ---

def test_parse_tail():
    node = asg.parse_line('show last 3 lines of data.txt')
    if not isinstance(node, TailLines):
        return f"expected TailLines, got {type(node).__name__}"
    if node.count != 3 or node.name != 'data.txt':
        return f"name={node.name}, count={node.count}"
    return True

def test_parse_filter():
    node = asg.parse_line('exclude lines matching "error" from log.txt')
    if not isinstance(node, FilterLines):
        return f"expected FilterLines, got {type(node).__name__}"
    if node.pattern != 'error' or node.name != 'log.txt':
        return f"name={node.name}, pattern={node.pattern}"
    return True

def test_parse_ifvar():
    node = asg.parse_line('if $N > 10 then count lines in data.txt otherwise count words in data.txt')
    if not isinstance(node, IfVar):
        return f"expected IfVar, got {type(node).__name__}"
    if node.var_name != 'N' or node.op != '>' or node.threshold != 10:
        return f"var={node.var_name}, op={node.op}, threshold={node.threshold}"
    return True


# --- Phase B: Interpreter Execution ---

def test_interp_tail():
    with tempfile.TemporaryDirectory() as tmp:
        os.chdir(tmp)
        _make_file(tmp, 'data.txt', 'alpha\nbeta\ngamma\ndelta\nepsilon')
        result = execute(asg.parse('show last 2 lines of data.txt'))
        return _assert_eq(result.strip(), 'delta epsilon')

def test_interp_filter():
    with tempfile.TemporaryDirectory() as tmp:
        os.chdir(tmp)
        _make_file(tmp, 'log.txt', 'info: starting\nerror: crashed\ninfo: restart\nwarn: low mem')
        result = execute(asg.parse('exclude lines matching "error" from log.txt'))
        return _assert_eq(result.strip(), 'info: starting info: restart warn: low mem')

def test_interp_ifvar_true():
    with tempfile.TemporaryDirectory() as tmp:
        os.chdir(tmp)
        _make_file(tmp, 'data.txt', 'a\nb\nc\nd\ne')
        src = 'set N = count lines in data.txt\nif $N > 3 then read file data.txt otherwise count words in data.txt'
        result = execute(asg.parse(src))
        return _assert_eq(result.strip().split('\n')[-1], 'a b c d e')

def test_interp_ifvar_false():
    with tempfile.TemporaryDirectory() as tmp:
        os.chdir(tmp)
        _make_file(tmp, 'data.txt', 'a\nb\nc\nd\ne')
        src = 'set N = count lines in data.txt\nif $N > 10 then read file data.txt otherwise count words in data.txt'
        result = execute(asg.parse(src))
        return _assert_eq(result.strip().split('\n')[-1], '5')

def test_interp_ifvar_ge():
    with tempfile.TemporaryDirectory() as tmp:
        os.chdir(tmp)
        _make_file(tmp, 'nums.txt', '1\n2\n3')
        src = 'set S = sum numbers in nums.txt\nif $S >= 6 then read file nums.txt otherwise count words in nums.txt'
        result = execute(asg.parse(src))
        return _assert_eq(result.strip().split('\n')[-1], '1 2 3')

def test_interp_ifvar_eq():
    with tempfile.TemporaryDirectory() as tmp:
        os.chdir(tmp)
        _make_file(tmp, 'data.txt', 'a\nb\nc')
        src = 'set N = count lines in data.txt\nif $N == 3 then count words in data.txt otherwise read file data.txt'
        result = execute(asg.parse(src))
        return _assert_eq(result.strip().split('\n')[-1], '3')


# --- Phase C: Terminal Backend Codegen ---

def test_shell_tail_codegen():
    nodes = [TailLines(name='data.txt', count=2)]
    code = compile_to_shell(nodes)
    if 'tail -n 2' not in code:
        return "expected 'tail -n 2' in shell code"
    return True

def test_shell_filter_codegen():
    nodes = [FilterLines(name='log.txt', pattern='error')]
    code = compile_to_shell(nodes)
    if 'grep -v' not in code:
        return "expected 'grep -v' in shell code"
    return True

def test_shell_ifvar_codegen():
    nodes = [IfVar(var_name='N', op='>', threshold=10,
                   then_branch=[asg.parse_line('count lines in data.txt')],
                   else_branch=[asg.parse_line('count words in data.txt')])]
    code = compile_to_shell(nodes)
    if '-gt' not in code or '_mk_var_N' not in code:
        return "expected '-gt' and '_mk_var_N' in shell code"
    return True


# --- Phase D: Python Backend Codegen ---

def test_python_tail_codegen():
    nodes = [TailLines(name='data.txt', count=2)]
    code = compile_to_python(nodes)
    if '_lines[-2:]' not in code:
        return "expected '_lines[-2:]' in python code"
    return True

def test_python_filter_codegen():
    nodes = [FilterLines(name='log.txt', pattern='error')]
    code = compile_to_python(nodes)
    if 'not in' not in code:
        return "expected 'not in' in python code"
    return True

def test_python_ifvar_codegen():
    nodes = [IfVar(var_name='N', op='>', threshold=10,
                   then_branch=[asg.parse_line('count lines in data.txt')],
                   else_branch=[asg.parse_line('count words in data.txt')])]
    code = compile_to_python(nodes)
    if '_vars.get' not in code or '_val > 10' not in code:
        return "expected '_vars.get' and '_val > 10' in python code"
    return True


# --- Phase E: SQL Backend Codegen ---

def test_sql_tail_codegen():
    nodes = [TailLines(name='data.txt', count=2)]
    code = compile_to_sql(nodes)
    if 'LIMIT 2' not in code:
        return "expected 'LIMIT 2' in sql code"
    return True

def test_sql_filter_codegen():
    nodes = [FilterLines(name='log.txt', pattern='error')]
    code = compile_to_sql(nodes)
    if 'NOT LIKE' not in code:
        return "expected 'NOT LIKE' in sql code"
    return True


# --- Phase F: Cross-Target Invariants ---

def test_cross_target_tail():
    with tempfile.TemporaryDirectory() as tmp:
        os.chdir(tmp)
        _make_file(tmp, 'data.txt', 'one\ntwo\nthree\nfour')
        interp_out = execute(asg.parse('show last 2 lines of data.txt'))
        shell_code = compile_to_shell(asg.parse('show last 2 lines of data.txt'))
        script_path = os.path.join(tmp, '_test.sh')
        with open(script_path, 'w') as f:
            f.write(shell_code)
        os.system(f'chmod +x {script_path}')
        shell_out = os.popen(f'/bin/sh {script_path} 2>/dev/null').read()
        if interp_out.strip() != shell_out.strip():
            return f"interp='{interp_out.strip()}' vs shell='{shell_out.strip()}'"
        return True

def test_cross_target_filter():
    with tempfile.TemporaryDirectory() as tmp:
        os.chdir(tmp)
        _make_file(tmp, 'log.txt', 'good\nbad\nok\nbad\nfine')
        interp_out = execute(asg.parse('exclude lines matching "bad" from log.txt'))
        shell_code = compile_to_shell(asg.parse('exclude lines matching "bad" from log.txt'))
        script_path = os.path.join(tmp, '_test.sh')
        with open(script_path, 'w') as f:
            f.write(shell_code)
        shell_out = os.popen(f'/bin/sh {script_path} 2>/dev/null').read()
        if interp_out.strip() != shell_out.strip():
            return f"interp='{interp_out.strip()}' vs shell='{shell_out.strip()}'"
        return True


# --- Phase G: End-to-End Data-Dependent Branching ---

def test_e2e_branch_on_line_count():
    with tempfile.TemporaryDirectory() as tmp:
        os.chdir(tmp)
        _make_file(tmp, 'data.txt', 'a\nb\nc\nd\ne\nf\ng\nh\ni\nj\nk')
        src = ('set N = count lines in data.txt\n'
               'if $N > 10 then create file big.txt with content "large file" '
               'otherwise create file small.txt with content "small file"')
        execute(asg.parse(src))
        if not os.path.exists(os.path.join(tmp, 'big.txt')):
            return "then_branch not executed (big.txt not created)"
        if os.path.exists(os.path.join(tmp, 'small.txt')):
            return "else_branch should NOT have executed"
        return True

def test_e2e_branch_on_sum():
    with tempfile.TemporaryDirectory() as tmp:
        os.chdir(tmp)
        _make_file(tmp, 'nums.txt', '10\n20\n30')
        src = ('set TOTAL = sum numbers in nums.txt\n'
               'if $TOTAL >= 50 then create file pass.txt with content "ok" '
               'otherwise create file fail.txt with content "fail"')
        execute(asg.parse(src))
        if not os.path.exists(os.path.join(tmp, 'pass.txt')):
            return "then_branch not executed (pass.txt not created)"
        return True

def test_e2e_ifvar_neq():
    with tempfile.TemporaryDirectory() as tmp:
        os.chdir(tmp)
        _make_file(tmp, 'data.txt', 'a\nb\nc')
        src = ('set N = count lines in data.txt\n'
               'if $N != 5 then create file note.txt with content "not five" '
               'otherwise create file note5.txt with content "five"')
        execute(asg.parse(src))
        if not os.path.exists(os.path.join(tmp, 'note.txt')):
            return "then_branch (!=) not executed"
        return True


# --- Phase H: Edge Cases ---

def test_edge_tail_overflow():
    with tempfile.TemporaryDirectory() as tmp:
        os.chdir(tmp)
        _make_file(tmp, 'short.txt', 'a\nb')
        result = execute(asg.parse('show last 10 lines of short.txt'))
        return _assert_eq(result.strip(), 'a b')

def test_edge_filter_no_matches():
    with tempfile.TemporaryDirectory() as tmp:
        os.chdir(tmp)
        _make_file(tmp, 'data.txt', 'error 1\nerror 2\nerror 3')
        result = execute(asg.parse('exclude lines matching "error" from data.txt'))
        return _assert_eq(result.strip(), '')

def test_edge_ifvar_unset_var():
    with tempfile.TemporaryDirectory() as tmp:
        os.chdir(tmp)
        _make_file(tmp, 'data.txt', 'hello')
        src = 'if $UNSET > 5 then read file data.txt otherwise count words in data.txt'
        result = execute(asg.parse(src))
        # Unset var defaults to 0. 0 > 5 is false → else_branch runs.
        # count words in "hello" = 1
        return _assert_eq(result.strip(), '1')


# --- Run ---

if __name__ == "__main__":
    print("=" * 60)
    print("v03.4 Test Suite — TailLines, FilterLines, IfVar")
    print("=" * 60)

    print("\n--- Phase A: ASG Parsing ---")
    run_rung("parse tail", test_parse_tail)
    run_rung("parse filter", test_parse_filter)
    run_rung("parse ifvar", test_parse_ifvar)

    print("\n--- Phase B: Interpreter Execution ---")
    run_rung("interp tail", test_interp_tail)
    run_rung("interp filter", test_interp_filter)
    run_rung("interp ifvar true", test_interp_ifvar_true)
    run_rung("interp ifvar false", test_interp_ifvar_false)
    run_rung("interp ifvar >=", test_interp_ifvar_ge)
    run_rung("interp ifvar ==", test_interp_ifvar_eq)

    print("\n--- Phase C: Terminal Backend Codegen ---")
    run_rung("shell tail codegen", test_shell_tail_codegen)
    run_rung("shell filter codegen", test_shell_filter_codegen)
    run_rung("shell ifvar codegen", test_shell_ifvar_codegen)

    print("\n--- Phase D: Python Backend Codegen ---")
    run_rung("python tail codegen", test_python_tail_codegen)
    run_rung("python filter codegen", test_python_filter_codegen)
    run_rung("python ifvar codegen", test_python_ifvar_codegen)

    print("\n--- Phase E: SQL Backend Codegen ---")
    run_rung("sql tail codegen", test_sql_tail_codegen)
    run_rung("sql filter codegen", test_sql_filter_codegen)

    print("\n--- Phase F: Cross-Target Invariants ---")
    run_rung("cross-target tail", test_cross_target_tail)
    run_rung("cross-target filter", test_cross_target_filter)

    print("\n--- Phase G: End-to-End Data-Dependent Branching ---")
    run_rung("e2e branch on line count", test_e2e_branch_on_line_count)
    run_rung("e2e branch on sum", test_e2e_branch_on_sum)
    run_rung("e2e ifvar !=", test_e2e_ifvar_neq)

    print("\n--- Phase H: Edge Cases ---")
    run_rung("edge tail overflow", test_edge_tail_overflow)
    run_rung("edge filter no matches", test_edge_filter_no_matches)
    run_rung("edge ifvar unset var", test_edge_ifvar_unset_var)

    print("\n" + "=" * 60)
    total = _passed + _failed
    if _failed == 0:
        print(f"  ALL {total} RUNGS GREEN ✅")
    else:
        print(f"  {_passed}/{total} passed, {_failed} FAILED")
        for name, reason in _failures:
            print(f"    FAIL: {name}: {reason}")
    print("=" * 60)
