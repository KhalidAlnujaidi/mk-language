#!/usr/bin/env python3
"""MK — unified front-door CLI for the NL→OS translation system.

Usage:
  python3 mk.py "backup data.txt"           # one-shot: plan + execute
  python3 mk.py                             # REPL: interactive prompt
  python3 mk.py --plan "inspect x.txt"      # show plan without executing
  python3 mk.py --no-llm "..."              # deterministic rules only
  python3 mk.py --backend shell "wc f.txt"  # compile to shell script
  python3 mk.py --backend python "wc f.txt" # compile to Python source
  python3 mk.py --backend sql "wc f.txt"    # compile to SQL queries
  python3 mk.py --show-all "count lines.."  # show all 4 backend outputs

The pipeline: NL input → Planner (decompose) → ASG (parse) → Backend (compile/execute)

Backends:
  direct   — execute immediately via the interpreter (default)
  shell    — compile to /bin/sh script (and optionally execute)
  python   — compile to standalone Python source
  sql      — compile to SQLite SQL script

  REPL commands:
    :help        Show available compound shortcuts
    :vocab       Show the full ASG vocabulary the parser understands
    :plan QUERY  Show decomposition without executing
    :backend X   Switch active backend (direct/shell/python/sql)
    :show-all Q  Show compiled output for all 4 backends
    :quit        Exit the REPL
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from planner import Planner, Plan, ASG_VOCABULARY, _COMPOUND_RULES
import asg
from interpreter import execute
from terminal_backend import compile_to_shell
from python_backend import compile_to_python
from sql_backend import compile_to_sql

VALID_BACKENDS = ("direct", "shell", "python", "sql")

# ---------------------------------------------------------------------------
# Banner
# ---------------------------------------------------------------------------

BANNER = """\
╔══════════════════════════════════════════════════════════════╗
║  MK — Natural Language → Operating System                   ║
║  Type intent in plain English. Type :help for shortcuts.     ║
║  Type :quit to exit.                                         ║
╚══════════════════════════════════════════════════════════════╝
"""

# ---------------------------------------------------------------------------
# Help — list all compound shortcuts
# ---------------------------------------------------------------------------

SHORTCUTS_HELP = """\
Compound shortcuts (deterministic — no model needed):

  backup NAME                  copy NAME → backup_NAME
  backup NAME to DEST          copy NAME → DEST
  duplicate NAME               copy NAME → copy_of_NAME
  rename OLD to NEW            copy + delete OLD
  safe delete NAME             delete with confirmation

  inspect NAME                 read + count lines + count words
  summarize NAME               read + lines + words + sum numbers
  stats for NAME               count lines + count words
  file info for NAME           count lines + count words
  wc NAME                      count lines + count words
  wordcount NAME               count words
  linecount NAME               count lines

  head NAME                    show first 10 lines
  head N NAME                  show first N lines
  first line of NAME           show first 1 line
  total NAME                   sum numbers in file
  sort NAME                    sort lines alphabetically
  grep "TEXT" in NAME          extract matching lines
  search for "TEXT"            find files containing text

  init project NAME            mkdir + create README
  create and read NAME "TEXT"  create file then read it back
  create empty NAME            create file with no content
  write "TEXT" to NAME         create file with content

  ensure NAME exists           create if missing (conditional)
  ensure NAME with "TEXT"      create with content if missing
  touch NAME                   create if missing, count if exists
  upsert NAME with "TEXT"      append if exists, create if missing

  backup A and B               batch backup two files
  inspect A and B              inspect two files

Conjunctions (auto-split):
  X then Y                     → step X, then step Y
  X and then Y                 → same
  X; Y                         → semicolon separator
  X → Y                        → arrow separator

Also accepts any raw ASG intent directly (see :vocab).

Backends (--backend or :backend):
  direct   — execute via interpreter (default)
  shell    — compile to /bin/sh
  python   — compile to Python source
  sql      — compile to SQLite SQL
"""


# ---------------------------------------------------------------------------
# Compilation helpers
# ---------------------------------------------------------------------------

def compile_to_backend(nodes: list[asg.ASGNode], backend: str) -> str:
    """Compile ASG nodes to the specified target backend's output."""
    if not nodes:
        return "(no nodes)"
    if backend == "shell":
        return compile_to_shell(nodes)
    elif backend == "python":
        return compile_to_python(nodes)
    elif backend == "sql":
        return compile_to_sql(nodes)
    elif backend == "direct":
        return "(direct execution — no compilation)"
    return f"(unknown backend: {backend})"


def show_all_backends(nodes: list[asg.ASGNode]):
    """Show compiled output for all four backends."""
    for backend in VALID_BACKENDS:
        print(f"\n  ── {backend} {'═' * (50 - len(backend))}")
        code = compile_to_backend(nodes, backend)
        for line in code.split('\n'):
            print(f"  │ {line}")


# ---------------------------------------------------------------------------
# Execution
# ---------------------------------------------------------------------------

def run_request(planner: Planner, request: str,
                show_plan: bool = False,
                quiet: bool = False,
                backend: str = "direct",
                show_all: bool = False) -> str:
    """Plan and optionally execute a request. Returns output string."""
    plan = planner.plan(request)

    if not plan.steps:
        if not quiet:
            print("  (empty plan — nothing to do)")
        return ""

    source_tag = plan.source
    if plan.notes:
        source_tag += f" ({plan.notes})"

    if show_plan or not quiet:
        print(f"  [{source_tag}] → {len(plan.steps)} step"
              f"{'s' if len(plan.steps) != 1 else ''}")
        if show_plan:
            for i, step in enumerate(plan.steps, 1):
                print(f"    {i}. {step}")

    nodes = plan.to_nodes()

    if show_all:
        show_all_backends(nodes)
        return ""

    if backend == "direct":
        output = execute(nodes)
        if output:
            for line in output.rstrip().split('\n'):
                print(f"  → {line}")
        elif not quiet and not show_plan:
            print("  → (ok)")
        return output
    else:
        # Compile to target backend
        code = compile_to_backend(nodes, backend)
        print(f"\n  ── {backend} output {'═' * max(0, 50 - len(backend) - 8)}")
        for line in code.split('\n'):
            print(f"  │ {line}")
        return code


# ---------------------------------------------------------------------------
# REPL
# ---------------------------------------------------------------------------

def repl(use_llm: bool = True):
    """Interactive read-eval-print loop."""
    planner = Planner(use_llm=use_llm)
    backend = "direct"

    print(BANNER)
    print(f"  Active backend: {backend}")

    while True:
        try:
            prompt = f"mk[{backend}]> " if backend != "direct" else "mk> "
            line = input(prompt).strip()
        except (EOFError, KeyboardInterrupt):
            print("\nBye.")
            break

        if not line:
            continue

        # REPL commands
        if line in (":quit", ":q"):
            print("Bye.")
            break

        if line in (":help", ":h", "help"):
            print(SHORTCUTS_HELP)
            continue

        if line in (":vocab", ":v"):
            print(ASG_VOCABULARY)
            continue

        if line.startswith(":plan "):
            request = line[6:].strip()
            if request:
                run_request(planner, request, show_plan=True, backend=backend)
            continue

        if line.startswith(":backend "):
            new_backend = line[9:].strip().lower()
            if new_backend in VALID_BACKENDS:
                backend = new_backend
                print(f"  Backend → {backend}")
            else:
                print(f"  Unknown backend '{new_backend}'. Choose: {', '.join(VALID_BACKENDS)}")
            continue

        if line.startswith(":show-all "):
            request = line[10:].strip()
            if request:
                run_request(planner, request, show_all=True, quiet=True)
            continue

        # Execute the request with the active backend
        run_request(planner, line, backend=backend)


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def main():
    import argparse
    parser = argparse.ArgumentParser(
        description="MK — Natural Language to Operating System translator",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=SHORTCUTS_HELP,
    )
    parser.add_argument("request", nargs="?", default=None,
                        help="Natural-language request (omit for REPL mode)")
    parser.add_argument("--plan", "-p", action="store_true",
                        help="Show decomposition plan without executing")
    parser.add_argument("--no-llm", action="store_true",
                        help="Disable LLM fallback (deterministic rules only)")
    parser.add_argument("--quiet", "-q", action="store_true",
                        help="Suppress plan info, show output only")
    parser.add_argument("--backend", "-b", default="direct",
                        choices=VALID_BACKENDS,
                        help="Target backend: direct (execute), shell, python, sql")
    parser.add_argument("--show-all", "-a", action="store_true",
                        help="Show compiled output for ALL backends")
    args = parser.parse_args()

    if args.request is None:
        repl(use_llm=not args.no_llm)
    else:
        planner = Planner(use_llm=not args.no_llm)
        run_request(planner, args.request,
                    show_plan=args.plan, quiet=args.quiet,
                    backend=args.backend, show_all=args.show_all)


if __name__ == "__main__":
    main()
