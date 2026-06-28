#!/usr/bin/env python3
"""Planner test suite — deterministic decomposition + passthrough + LLM integration.

Phase G:  Planner deterministic rules (compound intents → known decomposition)
Phase G+: Conjunction splitting (multi-clause sentences)
Phase H:  Passthrough (single valid intents pass through unchanged)
Phase I:  End-to-end plan→execute (deterministic plans produce correct output)
Phase J:  LLM integration (if Ollama is available — marked as integration)
Phase K:  New compound rules (conditional, batch, rename, shortcuts)
Phase L:  End-to-end for new rules (conditional + batch + rename)
Phase M:  mk.py CLI smoke tests
Phase N:  Multi-backend CLI (--backend shell/python/sql, --show-all)

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
from terminal_backend import compile_to_shell
from python_backend import compile_to_python
from sql_backend import compile_to_sql

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
    results.append("\nPhase H: Passthrough (single intents)")
    planner = Planner(use_llm=False)

    passthrough_tests = [
        ('create file test.txt with content "hello"'),
        ('read file data.txt'),
        ('append "more" to log.txt'),
        ('count lines in report.txt'),
        ('count words in essay.txt'),
        ('sort lines in names.txt'),
        ('show first 5 lines of log.txt'),
        ('sum numbers in prices.txt'),
        ('extract lines matching "error" from system.log'),
        ('copy source.txt to dest.txt'),
    ]

    for intent in passthrough_tests:
        plan = planner.plan(intent)
        test(f"passthrough: {intent[:40]}",
             plan.source == "passthrough" and
             len(plan.steps) == 1 and
             plan.steps[0] == intent,
             f"got source={plan.source}, steps={plan.steps}")


# ---------------------------------------------------------------------------
# Phase I: End-to-end plan→execute
# ---------------------------------------------------------------------------

def phase_i():
    results.append("\nPhase I: End-to-End Plan→Execute")
    planner = Planner(use_llm=False)

    def e2e_test(name: str, request: str, setup_fn, expected: str):
        def _run():
            if setup_fn:
                setup_fn()
            output = planner.plan_and_execute(request)
            test(f"e2e:{name}",
                 output.strip() == expected,
                 f"expected '{expected}', got '{output.strip()}'")
        run_in_sandbox(_run)

    # backup: create file → backup it → verify backup exists
    e2e_test("backup",
             "backup data.txt",
             lambda: _create_file("data.txt", "content"),
             "")

    # file info: create file with known content → count lines + words
    e2e_test("file-info",
             "file info for doc.txt",
             lambda: _create_file("doc.txt", "hello world\nfoo bar"),
             "2\n4")

    # stats: same
    e2e_test("stats",
             "stats for data.txt",
             lambda: _create_file("data.txt", "one two three"),
             "1\n3")

    # create and read
    e2e_test("create-and-read",
             'create and read test.txt with content "hello"',
             None,
             "hello")

    # inspect: read + count lines + count words
    e2e_test("inspect",
             "inspect page.txt",
             lambda: _create_file("page.txt", "alpha beta\ngamma"),
             "alpha beta gamma\n2\n3")

    # wc
    e2e_test("wc",
             "wc doc.txt",
             lambda: _create_file("doc.txt", "one two\nthree four five"),
             "2\n5")

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


# ---------------------------------------------------------------------------
# Phase K: New compound rules (conditional, batch, rename, shortcuts)
# ---------------------------------------------------------------------------

def phase_k():
    results.append("\nPhase K: New Compound Rules (v2)")
    planner = Planner(use_llm=False)

    # summarize NAME → read + lines + words + sum
    plan = planner.plan("summarize sales.txt")
    test("summarize → 4 steps",
         plan.source == "deterministic" and len(plan.steps) == 4 and
         "read file sales.txt" in plan.steps[0],
         f"got {plan}")

    # first line of NAME → show first 1 lines
    plan = planner.plan("first line of readme.txt")
    test("first-line-of → show first 1",
         plan.source == "deterministic" and
         "show first 1 lines of readme.txt" in plan.steps[0],
         f"got {plan}")

    # ensure NAME exists → conditional
    plan = planner.plan("ensure config.txt exists")
    test("ensure-exists → conditional",
         plan.source == "deterministic" and len(plan.steps) == 1 and
         "if config.txt exists" in plan.steps[0] and
         "otherwise create file config.txt" in plan.steps[0],
         f"got {plan}")

    # ensure NAME with content TEXT → conditional
    plan = planner.plan('ensure app.conf with content "debug=true"')
    test("ensure-with-content → conditional",
         plan.source == "deterministic" and len(plan.steps) == 1 and
         "if app.conf exists" in plan.steps[0] and
         'create file app.conf with content "debug=true"' in plan.steps[0],
         f"got {plan}")

    # touch NAME → conditional
    plan = planner.plan("touch new.txt")
    test("touch → conditional",
         plan.source == "deterministic" and len(plan.steps) == 1 and
         "if new.txt exists" in plan.steps[0] and
         "otherwise create file new.txt" in plan.steps[0],
         f"got {plan}")

    # upsert NAME with TEXT → conditional append/create
    plan = planner.plan('upsert log.txt with "new entry"')
    test("upsert → conditional append/create",
         plan.source == "deterministic" and len(plan.steps) == 1 and
         "if log.txt exists" in plan.steps[0] and
         'append "new entry" to log.txt' in plan.steps[0] and
         'create file log.txt with content "new entry"' in plan.steps[0],
         f"got {plan}")

    # rename OLD to NEW → copy + delete
    plan = planner.plan("rename old.txt to new.txt")
    test("rename → copy + delete",
         plan.source == "deterministic" and len(plan.steps) == 2 and
         "copy old.txt to new.txt" in plan.steps[0] and
         "delete old.txt confirm" in plan.steps[1],
         f"got {plan}")

    # create empty NAME → create with empty content
    plan = planner.plan("create empty placeholder.txt")
    test("create-empty → create with empty content",
         plan.source == "deterministic" and len(plan.steps) == 1 and
         'create file placeholder.txt with content ""' in plan.steps[0],
         f"got {plan}")

    # write TEXT to NAME → create file
    plan = planner.plan('write "hello world" to greeting.txt')
    test("write → create file",
         plan.source == "deterministic" and len(plan.steps) == 1 and
         'create file greeting.txt with content "hello world"' in plan.steps[0],
         f"got {plan}")

    # linecount NAME → count lines
    plan = planner.plan("linecount report.txt")
    test("linecount → count lines",
         plan.source == "deterministic" and
         "count lines in report.txt" in plan.steps[0],
         f"got {plan}")

    # lines in NAME → count lines
    plan = planner.plan("lines in report.txt")
    test("lines-in → count lines",
         plan.source == "deterministic" and
         "count lines in report.txt" in plan.steps[0],
         f"got {plan}")

    # words in NAME → count words
    plan = planner.plan("words in report.txt")
    test("words-in → count words",
         plan.source == "deterministic" and
         "count words in report.txt" in plan.steps[0],
         f"got {plan}")

    # backup A and B → two copies
    plan = planner.plan("backup alpha.txt and beta.txt")
    test("backup-ab → batch copy",
         plan.source == "deterministic" and len(plan.steps) == 2 and
         "copy alpha.txt to backup_alpha.txt" in plan.steps[0] and
         "copy beta.txt to backup_beta.txt" in plan.steps[1],
         f"got {plan}")

    # inspect A and B → 6 steps (3 per file)
    plan = planner.plan("inspect file1.txt and file2.txt")
    test("inspect-ab → batch inspect",
         plan.source == "deterministic" and len(plan.steps) == 6 and
         "read file file1.txt" in plan.steps[0] and
         "read file file2.txt" in plan.steps[3],
         f"got {plan}")


# ---------------------------------------------------------------------------
# Phase L: End-to-end for new rules
# ---------------------------------------------------------------------------

def phase_l():
    results.append("\nPhase L: New Rules End-to-End")
    planner = Planner(use_llm=False)

    def e2e_test(name: str, request: str, setup_fn, expected: str):
        def _run():
            if setup_fn:
                setup_fn()
            output = planner.plan_and_execute(request)
            test(f"e2e:{name}",
                 output.strip() == expected,
                 f"expected '{expected}', got '{output.strip()}'")
        run_in_sandbox(_run)

    # summarize: read + lines + words + sum
    e2e_test("summarize",
             "summarize sales.txt",
             lambda: _create_file("sales.txt", "10 20\n30 40"),
             "10 20 30 40\n2\n4\n100")

    # first line of NAME
    e2e_test("first-line-of",
             "first line of config.txt",
             lambda: _create_file("config.txt", "first_setting=true\nsecond=false"),
             "first_setting=true")

    # ensure NAME exists — file missing → creates it
    e2e_test("ensure-creates",
             "ensure new.txt exists",
             None,
             "")

    # ensure NAME exists — file already exists → reads it
    e2e_test("ensure-reads",
             "ensure data.txt exists",
             lambda: _create_file("data.txt", "hello"),
             "hello")

    # touch NAME — file exists → counts lines
    e2e_test("touch-exists",
             "touch existing.txt",
             lambda: _create_file("existing.txt", "line1\nline2"),
             "2")

    # touch NAME — file missing → creates empty
    e2e_test("touch-creates",
             "touch fresh.txt",
             None,
             "")

    # upsert — file exists → appends
    e2e_test("upsert-appends",
             'upsert notes.txt with "new"',
             lambda: _create_file("notes.txt", "old"),
             "")

    # upsert — file missing → creates
    e2e_test("upsert-creates",
             'upsert fresh.txt with "first"',
             None,
             "")

    # rename → copy + delete original
    e2e_test("rename",
             "rename old.dat to new.dat",
             lambda: _create_file("old.dat", "payload"),
             "")

    # create empty → creates empty file
    e2e_test("create-empty",
             "create empty blank.txt",
             None,
             "")

    # write "TEXT" to NAME → creates file
    e2e_test("write-to",
             'write "test data" to sample.txt',
             None,
             "")

    # linecount
    e2e_test("linecount",
             "linecount code.py",
             lambda: _create_file("code.py", "a\nb\nc\nd"),
             "4")

    # lines in NAME
    e2e_test("lines-in",
             "lines in data.txt",
             lambda: _create_file("data.txt", "x\ny"),
             "2")

    # words in NAME
    e2e_test("words-in",
             "words in data.txt",
             lambda: _create_file("data.txt", "one two three"),
             "3")

    # backup A and B → both copied
    e2e_test("backup-ab",
             "backup a.txt and b.txt",
             lambda: (
                 _create_file("a.txt", "A"),
                 _create_file("b.txt", "B"),
             ),
             "")


# ---------------------------------------------------------------------------
# Phase M: mk.py CLI smoke tests
# ---------------------------------------------------------------------------

def phase_m():
    results.append("\nPhase M: mk.py CLI Smoke Tests")

    def run_cli(args: list[str], cwd: Path) -> tuple[int, str]:
        """Run mk.py in a specific cwd, return (exit_code, combined output)."""
        proc = subprocess.run(
            [PYTHON, str(HERE / "mk.py")] + args,
            capture_output=True, text=True, cwd=str(cwd), timeout=10,
        )
        return proc.returncode, (proc.stdout + proc.stderr).strip()

    def cli_test(name: str, args: list[str], setup_fn,
                 expected_contains: str = None,
                 expected_exit: int = 0):
        def _run():
            if setup_fn:
                setup_fn()
            code, output = run_cli(args, Path(os.getcwd()))
            ok = code == expected_exit
            if expected_contains is not None:
                ok = ok and expected_contains in output
            test(f"cli:{name}", ok,
                 f"exit={code}, output='{output[:120]}'")
        run_in_sandbox(_run)

    # One-shot: simple passthrough
    cli_test("oneshot-create",
             ['create file hello.txt with content "world"'],
             None)

    # One-shot: with --quiet flag
    cli_test("oneshot-quiet",
             ['-q', 'create file x.txt with content "1"'],
             None)

    # One-shot: compound rule with --plan (show decomposition)
    cli_test("plan-inspect",
             ['-p', 'inspect data.txt'],
             lambda: _create_file("data.txt", "content"),
             expected_contains="read file")

    # One-shot: backup
    cli_test("backup",
             ['-q', 'backup data.txt'],
             lambda: _create_file("data.txt", "content"))

    # --help shows shortcuts
    cli_test("help",
             ['--help'],
             None,
             expected_contains="backup")

    # REPL mode: pipe commands via stdin
    def test_repl():
        work = Path(tempfile.mkdtemp(prefix="mk_repl_"))
        old_cwd = os.getcwd()
        try:
            os.chdir(str(work))
            proc = subprocess.run(
                [PYTHON, str(HERE / "mk.py")],
                input='create file test.txt with content "hello"\nread file test.txt\n:quit\n',
                capture_output=True, text=True, timeout=10,
            )
            ok = "hello" in proc.stdout
            test("cli:repl-basic", ok,
                 f"output='{proc.stdout[:200]}'")
        finally:
            os.chdir(old_cwd)
            shutil.rmtree(work, ignore_errors=True)
    test_repl()

    # REPL :help command
    def test_repl_help():
        work = Path(tempfile.mkdtemp(prefix="mk_repl_"))
        old_cwd = os.getcwd()
        try:
            os.chdir(str(work))
            proc = subprocess.run(
                [PYTHON, str(HERE / "mk.py")],
                input=':help\n:quit\n',
                capture_output=True, text=True, timeout=10,
            )
            ok = "backup" in proc.stdout.lower()
            test("cli:repl-help", ok,
                 f"output='{proc.stdout[:200]}'")
        finally:
            os.chdir(old_cwd)
            shutil.rmtree(work, ignore_errors=True)
    test_repl_help()


# ---------------------------------------------------------------------------
# Phase N: Multi-backend CLI tests
# ---------------------------------------------------------------------------

def phase_n():
    results.append("\nPhase N: Multi-Backend CLI")

    def run_cli(args: list[str], cwd: Path) -> tuple[int, str]:
        proc = subprocess.run(
            [PYTHON, str(HERE / "mk.py")] + args,
            capture_output=True, text=True, cwd=str(cwd), timeout=10,
        )
        return proc.returncode, (proc.stdout + proc.stderr).strip()

    def backend_test(name: str, args: list[str], setup_fn,
                     expected_contains: str):
        def _run():
            if setup_fn:
                setup_fn()
            code, output = run_cli(args, Path(os.getcwd()))
            ok = code == 0 and expected_contains in output
            test(f"backend:{name}", ok,
                 f"exit={code}, looking for '{expected_contains}' "
                 f"in '{output[:160]}'")
        run_in_sandbox(_run)

    # --backend shell: compile to shell script
    backend_test("shell-count-lines",
                 ['-q', '--backend', 'shell', 'count lines in data.txt'],
                 lambda: _create_file("data.txt", "a\nb\nc"),
                 "awk")

    # --backend shell: create file
    backend_test("shell-create",
                 ['-q', '--backend', 'shell',
                  'create file x.txt with content "hello"'],
                 None,
                 "printf")

    # --backend python: compile to Python source
    backend_test("python-count-lines",
                 ['-q', '--backend', 'python', 'count lines in data.txt'],
                 lambda: _create_file("data.txt", "a\nb"),
                 "len(")

    # --backend python: create file
    backend_test("python-create",
                 ['-q', '--backend', 'python',
                  'create file y.txt with content "world"'],
                 None,
                 "open(")

    # --backend sql: compile to SQL
    backend_test("sql-count-lines",
                 ['-q', '--backend', 'sql', 'count lines in data.txt'],
                 lambda: _create_file("data.txt", "a\nb"),
                 "COUNT")

    # --backend sql: create table
    backend_test("sql-create",
                 ['-q', '--backend', 'sql',
                  'create file z.txt with content "data"'],
                 None,
                 "CREATE TABLE")

    # --show-all: shows all 4 backends
    backend_test("show-all-backends",
                 ['-q', '--show-all', 'count lines in f.txt'],
                 lambda: _create_file("f.txt", "x"),
                 "shell")

    def test_show_all_content():
        """Verify --show-all contains markers for all backends."""
        def _run():
            _create_file("test.txt", "hello\nworld")
            code, output = run_cli(
                ['-q', '--show-all', 'count lines in test.txt'],
                Path(os.getcwd()))
            has_shell = "shell" in output
            has_python = "python" in output
            has_sql = "sql" in output
            has_direct = "direct" in output
            ok = code == 0 and has_shell and has_python and has_sql and has_direct
            test("backend:show-all-has-all-4",
                 ok,
                 f"shell={has_shell} python={has_python} "
                 f"sql={has_sql} direct={has_direct}")
        run_in_sandbox(_run)
    test_show_all_content()

    # REPL :backend switching
    def test_repl_backend_switch():
        work = Path(tempfile.mkdtemp(prefix="mk_be_"))
        old_cwd = os.getcwd()
        try:
            os.chdir(str(work))
            _create_file("d.txt", "one\ntwo")
            proc = subprocess.run(
                [PYTHON, str(HERE / "mk.py")],
                input=':backend shell\ncount lines in d.txt\n:quit\n',
                capture_output=True, text=True, timeout=10,
            )
            ok = "awk" in proc.stdout
            test("backend:repl-switch", ok,
                 f"output='{proc.stdout[:200]}'")
        finally:
            os.chdir(old_cwd)
            shutil.rmtree(work, ignore_errors=True)
    test_repl_backend_switch()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

import json  # needed by phase_j


# ---------------------------------------------------------------------------
# Phase O: Iteration support (ForEachFile + GlobFiles)
# ---------------------------------------------------------------------------

def phase_o():
    results.append("\nPhase O: Iteration Support")
    planner = Planner(use_llm=False)

    # --- Iteration plan structure ---

    # "count lines in all *.txt" → ForEachFile node
    plan = planner.plan("count lines in all *.txt")
    test("iter-count-lines → iteration plan",
         plan.source == "iteration" and
         len(plan.extra_nodes) == 1 and
         isinstance(plan.extra_nodes[0], asg.ForEachFile),
         f"got source={plan.source}, nodes={plan.extra_nodes}")

    # Check the ForEachFile details
    if plan.extra_nodes:
        node = plan.extra_nodes[0]
        test("iter-count-lines → glob *.txt",
             node.glob_pattern == "*.txt",
             f"got glob={node.glob_pattern}")
        test("iter-count-lines → body has CountLines",
             len(node.body_template) == 1 and
             isinstance(node.body_template[0], asg.CountLines),
             f"got body={node.body_template}")
        test("iter-count-lines → placeholder {file}",
             node.placeholder == "{file}",
             f"got placeholder={node.placeholder}")

    # "read all *.log" → ForEachFile with ReadFile body
    plan = planner.plan("read all *.log")
    test("iter-read-all → iteration plan",
         plan.source == "iteration" and
         len(plan.extra_nodes) == 1 and
         isinstance(plan.extra_nodes[0], asg.ForEachFile),
         f"got {plan}")
    if plan.extra_nodes:
        node = plan.extra_nodes[0]
        test("iter-read-all → glob *.log",
             node.glob_pattern == "*.log",
             f"got glob={node.glob_pattern}")
        test("iter-read-all → body has ReadFile",
             isinstance(node.body_template[0], asg.ReadFile),
             f"got body={node.body_template}")

    # "inspect all *.txt" → multi-step body
    plan = planner.plan("inspect all *.txt")
    test("iter-inspect-all → 3 body nodes",
         plan.source == "iteration" and
         len(plan.extra_nodes) == 1 and
         len(plan.extra_nodes[0].body_template) == 3,
         f"got {plan}")

    # "backup all *.txt" → ForEachFile with CopyFile body
    plan = planner.plan("backup all *.txt")
    test("iter-backup-all → CopyFile body",
         plan.source == "iteration" and
         isinstance(plan.extra_nodes[0].body_template[0], asg.CopyFile),
         f"got {plan}")

    # "delete all *.txt" → ForEachFile with DeleteFile body (confirmed)
    plan = planner.plan("delete all *.txt")
    test("iter-delete-all → DeleteFile body",
         plan.source == "iteration" and
         isinstance(plan.extra_nodes[0].body_template[0], asg.DeleteFile) and
         plan.extra_nodes[0].body_template[0].confirm == True,
         f"got {plan}")

    # "sum numbers in all *.txt" → ForEachFile with SumNumbers body
    plan = planner.plan("sum numbers in all *.txt")
    test("iter-sum-all → SumNumbers body",
         plan.source == "iteration" and
         isinstance(plan.extra_nodes[0].body_template[0], asg.SumNumbers),
         f"got {plan}")

    # --- End-to-end execution ---

    def test_count_lines_all():
        for name, content in [('a.txt', 'line1\nline2'), ('b.txt', 'x\ny\nz'), ('c.log', 'one')]:
            with open(name, 'w') as f:
                f.write(content)
        output = planner.plan_and_execute('count lines in all *.txt')
        return ' '.join(output.split())

    result = run_in_sandbox(test_count_lines_all)
    test("e2e: count lines in all *.txt → '2 3'",
         result == '2 3',
         f"got '{result}'")

    def test_read_all():
        with open('x.log', 'w') as f:
            f.write('hello world')
        with open('y.log', 'w') as f:
            f.write('foo bar')
        with open('z.txt', 'w') as f:
            f.write('skip me')
        output = planner.plan_and_execute('read all *.log')
        return ' '.join(output.split())

    result = run_in_sandbox(test_read_all)
    test("e2e: read all *.log → 'hello world foo bar'",
         result == 'hello world foo bar',
         f"got '{result}'")

    def test_inspect_all():
        with open('d.txt', 'w') as f:
            f.write('hello world')
        output = planner.plan_and_execute('inspect all *.txt')
        return ' '.join(output.split())

    result = run_in_sandbox(test_inspect_all)
    test("e2e: inspect all *.txt → read+lines+words",
         result == 'hello world 1 2',
         f"got '{result}'")

    def test_backup_all():
        with open('orig.txt', 'w') as f:
            f.write('data')
        planner.plan_and_execute('backup all *.txt')
        # orig.txt should still exist, backup_orig.txt should now exist
        import os.path
        return os.path.exists('backup_orig.txt') and os.path.exists('orig.txt')

    result = run_in_sandbox(test_backup_all)
    test("e2e: backup all *.txt creates backup_ copies",
         result == True,
         f"got {result}")

    def test_sum_all():
        with open('n1.txt', 'w') as f:
            f.write('10 20')
        with open('n2.txt', 'w') as f:
            f.write('5 15')
        output = planner.plan_and_execute('sum numbers in all *.txt')
        return ' '.join(output.split())

    result = run_in_sandbox(test_sum_all)
    test("e2e: sum numbers in all *.txt → '30 20'",
         result == '30 20',
         f"got '{result}'")

    def test_delete_all():
        with open('todelete1.txt', 'w') as f:
            f.write('x')
        with open('todelete2.txt', 'w') as f:
            f.write('y')
        planner.plan_and_execute('delete all *.txt')
        import os.path
        return not os.path.exists('todelete1.txt') and not os.path.exists('todelete2.txt')

    result = run_in_sandbox(test_delete_all)
    test("e2e: delete all *.txt removes all matching",
         result == True,
         f"got {result}")

    # --- GlobFiles direct execution ---

    def test_glob_files():
        for name in ['a.txt', 'b.txt', 'c.log']:
            with open(name, 'w') as f:
                f.write('x')
        node = asg.GlobFiles(pattern='*.txt')
        from interpreter import execute
        output = execute([node])
        return ' '.join(output.split())

    result = run_in_sandbox(test_glob_files)
    test("glob *.txt → 'a.txt b.txt'",
         result == 'a.txt b.txt',
         f"got '{result}'")

    # --- Shell backend compilation of ForEachFile ---

    plan = planner.plan("count lines in all *.txt")
    nodes = plan.to_nodes()
    shell_code = compile_to_shell(nodes)
    test("shell backend: ForEachFile → for loop",
         "for _mk_f" in shell_code and "*.txt" in shell_code,
         f"got: {shell_code[:200]}")

    # --- Python backend compilation of ForEachFile ---

    py_code = compile_to_python(nodes)
    test("python backend: ForEachFile → for loop",
         "for _mk_f" in py_code and "fnmatch" in py_code,
         f"got: {py_code[:200]}")

    # --- SQL backend compilation of ForEachFile ---

    sql_code = compile_to_sql(nodes)
    test("sql backend: ForEachFile → comment + executor",
         "ForEachFile" in sql_code,
         f"got: {sql_code[:200]}")


def main():
    print("=" * 60)
    print("MK Planner Test Suite")
    print("=" * 60)

    phase_g()
    phase_g_plus()
    phase_h()
    phase_i()
    phase_j()
    phase_k()
    phase_l()
    phase_m()
    phase_n()
    phase_o()
    phase_n()

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
