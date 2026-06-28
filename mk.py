#!/usr/bin/env python3
"""MK — unified front-door CLI for the NL→OS translation system.

Usage:
  python3 mk.py "backup data.txt"       # one-shot: plan + execute
  python3 mk.py                         # REPL: interactive prompt
  python3 mk.py --plan "inspect x.txt"  # show plan without executing
  python3 mk.py --no-llm "..."          # deterministic rules only

The pipeline: NL input → Planner (decompose) → ASG (parse) → Interpreter (execute)

Features:
  - Human types natural language (compound, multi-step, or simple)
  - Planner decomposes into ASG-parseable steps (deterministic rules first,
    LLM fallback if enabled)
  - ASG parser compiles each step into a target-independent graph
  - Interpreter executes through the direct backend (OS operations)
  - Output is printed to stdout

  REPL commands:
    :help        Show available compound shortcuts
    :vocab       Show the full ASG vocabulary the parser understands
    :plan QUERY  Show decomposition without executing
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
"""


# ---------------------------------------------------------------------------
# Execution
# ---------------------------------------------------------------------------

def run_request(planner: Planner, request: str, show_plan: bool = False,
                quiet: bool = False) -> str:
    """Plan and optionally execute a request. Returns output string."""
    plan = planner.plan(request)

    if not plan.steps:
        if not quiet:
            print("  (empty plan — nothing to do)")
        return ""

    if show_plan or not quiet:
        source_tag = plan.source
        if plan.notes:
            source_tag += f" ({plan.notes})"
        print(f"  [{source_tag}] → {len(plan.steps)} step"
              f"{'s' if len(plan.steps) != 1 else ''}")
        if show_plan:
            for i, step in enumerate(plan.steps, 1):
                print(f"    {i}. {step}")

    # Execute
    output = planner.plan_and_execute(request)
    if output:
        for line in output.rstrip().split('\n'):
            print(f"  → {line}")
    elif not quiet and not show_plan:
        print("  → (ok)")

    return output


# ---------------------------------------------------------------------------
# REPL
# ---------------------------------------------------------------------------

def repl(use_llm: bool = True):
    """Interactive read-eval-print loop."""
    planner = Planner(use_llm=use_llm)

    print(BANNER)

    while True:
        try:
            line = input("mk> ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nBye.")
            break

        if not line:
            continue

        # REPL commands
        if line == ":quit" or line == ":q":
            print("Bye.")
            break

        if line == ":help" or line == ":h" or line == "help":
            print(SHORTCUTS_HELP)
            continue

        if line == ":vocab" or line == ":v":
            print(ASG_VOCABULARY)
            continue

        if line.startswith(":plan "):
            request = line[6:].strip()
            if request:
                run_request(planner, request, show_plan=True)
            continue

        # Execute the request
        run_request(planner, line)


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
    args = parser.parse_args()

    if args.request is None:
        # REPL mode
        repl(use_llm=not args.no_llm)
    else:
        # One-shot mode
        planner = Planner(use_llm=not args.no_llm)
        run_request(planner, args.request,
                    show_plan=args.plan, quiet=args.quiet)


if __name__ == "__main__":
    main()
