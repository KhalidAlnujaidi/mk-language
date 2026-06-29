#!/usr/bin/env python3
"""Test suite for pipeline patterns — capture output and reuse in subsequent steps.

Tests the planner's ability to decompose compound intents that chain operations
where the output of step 1 becomes input to step 2.

Phase P: Pipeline decomposition (planner → steps)
Phase PE: Pipeline end-to-end execution (sandbox)
"""

import os
import sys
import tempfile
import subprocess

sys.path.insert(0, os.path.dirname(__file__))

import asg
from interpreter import execute
from planner import Planner

passed = 0
failed = 0
failures = []


def check(label, got, expected):
    global passed, failed
    got_s = str(got).strip()
    exp_s = str(expected).strip()
    if got_s == exp_s:
        passed += 1
        print(f"  ✅ {label}")
    else:
        failed += 1
        failures.append(f"{label}: expected '{exp_s}', got '{got_s}'")
        print(f"  ❌ {label}: expected '{exp_s}', got '{got_s}'")


# ===========================================================================
# Phase P: Pipeline decomposition — verify planner produces correct steps
# ===========================================================================

def test_pipeline_decomposition():
    print("\nPhase P: Pipeline Decomposition (planner → steps)")
    p = Planner(use_llm=False)

    # "count lines in X and save to Y"
    plan = p.plan("count lines in data.txt and save to result.txt")
    check("pipe: count lines save to",
          plan.steps,
          ['set _pipe = count lines in data.txt', 'write "{_pipe}" to result.txt'])

    # "count words in X and save to Y"
    plan = p.plan("count words in data.txt and save to result.txt")
    check("pipe: count words save to",
          plan.steps,
          ['set _pipe = count words in data.txt', 'write "{_pipe}" to result.txt'])

    # "sum numbers in X and save to Y"
    plan = p.plan("sum numbers in data.txt and save to result.txt")
    check("pipe: sum numbers save to",
          plan.steps,
          ['set _pipe = sum numbers in data.txt', 'write "{_pipe}" to result.txt'])

    # "read X and save to Y"
    plan = p.plan("read data.txt and save to copy.txt")
    check("pipe: read save to",
          plan.steps,
          ['set _pipe = read file data.txt', 'write "{_pipe}" to copy.txt'])

    # "extract PATTERN from X and save to Y"
    plan = p.plan('extract "error" from log.txt and save to errors.txt')
    check("pipe: extract save to",
          plan.steps,
          ['set _pipe = extract lines matching "error" from log.txt',
           'write "{_pipe}" to errors.txt'])

    # "count lines in X then multiply by N"
    plan = p.plan("count lines in data.txt then multiply by 3")
    check("pipe: count lines multiply",
          plan.steps,
          ['set _n = count lines in data.txt', 'compute {_n} * 3'])

    # "sum numbers in X then multiply by N"
    plan = p.plan("sum numbers in data.txt then multiply by 2")
    check("pipe: sum multiply",
          plan.steps,
          ['set _total = sum numbers in data.txt', 'compute {_total} * 2'])

    # "count lines in X then add N"
    plan = p.plan("count lines in data.txt then add 10")
    check("pipe: count lines add",
          plan.steps,
          ['set _n = count lines in data.txt', 'compute {_n} + 10'])

    # "count lines in X and write result to Y"
    plan = p.plan("count lines in data.txt and write result to out.txt")
    check("pipe: count lines write result",
          plan.steps,
          ['set _n = count lines in data.txt', 'write "{_n}" to out.txt'])

    # "concat X and Y into Z"
    plan = p.plan("concat a.txt and b.txt into merged.txt")
    check("pipe: concat",
          plan.steps,
          ['set _a = read file a.txt', 'set _b = read file b.txt',
           'write "{_a} {_b}" to merged.txt'])

    # "merge X and Y into Z" (alias)
    plan = p.plan("merge a.txt and b.txt into merged.txt")
    check("pipe: merge alias",
          plan.steps,
          ['set _a = read file a.txt', 'set _b = read file b.txt',
           'write "{_a} {_b}" to merged.txt'])

    # "sort X and save to Y"
    plan = p.plan("sort data.txt and save to sorted.txt")
    check("pipe: sort save to",
          plan.steps,
          ['set _pipe = sort lines in data.txt', 'write "{_pipe}" to sorted.txt'])

    # "unique X and save to Y"
    plan = p.plan("unique data.txt and save to deduped.txt")
    check("pipe: unique save to",
          plan.steps,
          ['set _pipe = unique lines in data.txt', 'write "{_pipe}" to deduped.txt'])


# ===========================================================================
# Phase PE: Pipeline end-to-end execution (sandbox)
# ===========================================================================

def test_pipeline_e2e():
    print("\nPhase PE: Pipeline End-to-End (sandbox execution)")
    p = Planner(use_llm=False)

    # count lines and save to file
    with tempfile.TemporaryDirectory() as tmp:
        _mk(tmp, "data.txt", "one\ntwo\nthree")
        os.chdir(tmp)
        try:
            p.plan_and_execute("count lines in data.txt and save to result.txt")
            check("e2e: count lines save", _read("result.txt"), "3")
        finally:
            _restore_cwd()

    # sum numbers and save to file
    with tempfile.TemporaryDirectory() as tmp:
        _mk(tmp, "nums.txt", "10\n20\n30")
        os.chdir(tmp)
        try:
            p.plan_and_execute("sum numbers in nums.txt and save to total.txt")
            check("e2e: sum save", _read("total.txt"), "60")
        finally:
            _restore_cwd()

    # count lines then multiply by N
    with tempfile.TemporaryDirectory() as tmp:
        _mk(tmp, "data.txt", "a\nb\nc\nd")
        os.chdir(tmp)
        try:
            result = p.plan_and_execute("count lines in data.txt then multiply by 5")
            check("e2e: count multiply", result, "20")
        finally:
            _restore_cwd()

    # sum numbers then multiply by N
    with tempfile.TemporaryDirectory() as tmp:
        _mk(tmp, "nums.txt", "5\n10\n15")
        os.chdir(tmp)
        try:
            result = p.plan_and_execute("sum numbers in nums.txt then multiply by 2")
            check("e2e: sum multiply", result, "60")
        finally:
            _restore_cwd()

    # count lines then add N
    with tempfile.TemporaryDirectory() as tmp:
        _mk(tmp, "data.txt", "x\ny")
        os.chdir(tmp)
        try:
            result = p.plan_and_execute("count lines in data.txt then add 100")
            check("e2e: count add", result, "102")
        finally:
            _restore_cwd()

    # count lines and write result to file
    with tempfile.TemporaryDirectory() as tmp:
        _mk(tmp, "data.txt", "1\n2\n3\n4\n5")
        os.chdir(tmp)
        try:
            p.plan_and_execute("count lines in data.txt and write result to out.txt")
            check("e2e: write result", _read("out.txt"), "5")
        finally:
            _restore_cwd()

    # concat two files
    with tempfile.TemporaryDirectory() as tmp:
        _mk(tmp, "a.txt", "hello")
        _mk(tmp, "b.txt", "world")
        os.chdir(tmp)
        try:
            p.plan_and_execute("concat a.txt and b.txt into merged.txt")
            check("e2e: concat", _read("merged.txt"), "hello world")
        finally:
            _restore_cwd()

    # merge two files (alias)
    with tempfile.TemporaryDirectory() as tmp:
        _mk(tmp, "a.txt", "foo")
        _mk(tmp, "b.txt", "bar")
        os.chdir(tmp)
        try:
            p.plan_and_execute("merge a.txt and b.txt into combined.txt")
            check("e2e: merge", _read("combined.txt"), "foo bar")
        finally:
            _restore_cwd()

    # sort and save
    with tempfile.TemporaryDirectory() as tmp:
        _mk(tmp, "data.txt", "cherry\napple\nbanana")
        os.chdir(tmp)
        try:
            p.plan_and_execute("sort data.txt and save to sorted.txt")
            check("e2e: sort save", _read("sorted.txt"), "apple banana cherry")
        finally:
            _restore_cwd()

    # unique and save
    with tempfile.TemporaryDirectory() as tmp:
        _mk(tmp, "data.txt", "dup\ndup\nuniq\ndup")
        os.chdir(tmp)
        try:
            p.plan_and_execute("unique data.txt and save to deduped.txt")
            check("e2e: unique save", _read("deduped.txt"), "dup uniq")
        finally:
            _restore_cwd()

    # read and save (content copy)
    with tempfile.TemporaryDirectory() as tmp:
        _mk(tmp, "src.txt", "important data")
        os.chdir(tmp)
        try:
            p.plan_and_execute("read src.txt and save to dest.txt")
            check("e2e: read save", _read("dest.txt"), "important data")
        finally:
            _restore_cwd()

    # extract pattern and save
    with tempfile.TemporaryDirectory() as tmp:
        _mk(tmp, "log.txt", "INFO start\nERROR crash\nINFO done")
        os.chdir(tmp)
        try:
            p.plan_and_execute('extract "ERROR" from log.txt and save to errors.txt')
            check("e2e: extract save", _read("errors.txt"), "ERROR crash")
        finally:
            _restore_cwd()

    # count words and save
    with tempfile.TemporaryDirectory() as tmp:
        _mk(tmp, "data.txt", "hello world foo bar")
        os.chdir(tmp)
        try:
            p.plan_and_execute("count words in data.txt and save to wc.txt")
            check("e2e: count words save", _read("wc.txt"), "4")
        finally:
            _restore_cwd()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_cwd_stack = []

def _mk(tmpdir, name, content):
    path = os.path.join(tmpdir, name)
    with open(path, 'w') as f:
        f.write(content)

def _read(name):
    with open(name, 'r') as f:
        return f.read().strip()

def _restore_cwd():
    if _cwd_stack:
        os.chdir(_cwd_stack.pop())


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    print("=" * 60)
    print("  Pipeline Pattern Tests")
    print("=" * 60)

    _cwd_stack.append(os.getcwd())
    test_pipeline_decomposition()
    test_pipeline_e2e()

    print("\n" + "=" * 60)
    if failed == 0:
        print(f"  ALL {passed} RUNGS GREEN ✅")
    else:
        print(f"  {passed}/{passed + failed} passed, {failed} FAILED")
        for f in failures:
            print(f"    FAIL: {f}")
    print("=" * 60)
    sys.exit(1 if failed else 0)
