#!/usr/bin/env python3
"""Execution-verified data generation pipeline.

Takes the conformance rungs from the ASG test suite, parameterizes them
(varying filenames, contents, patterns, numbers), executes each variant
through all three backends (direct, shell, python), verifies the output
matches, and exports the verified triples as JSONL.

Each triple is a rejection-sampling data point:
  (intent, shell_command, python_code, expected_output, verified=True)

Unverified triples are dropped (not emitted). This is the moat — the raw
material for model distillation.

Usage:
    python generate_triples.py                    # → triples.jsonl (default)
    python generate_triples.py --out data.jsonl   # custom output
    python generate_triples.py --count 200        # target N triples
    python generate_triples.py --summary           # stats only, no file
"""
from __future__ import annotations

import argparse
import itertools
import json
import os
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Callable

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import asg
from asg import parse, ASGNode
from terminal_backend import compile_to_shell
from python_backend import compile_to_python


# ---------------------------------------------------------------------------
# Parameter pools — the variation axes
# ---------------------------------------------------------------------------

FILENAMES = [
    "notes.txt", "data.txt", "log.txt", "config.cfg", "output.dat",
    "report.md", "items.lst", "entries.log", "sample.txt", "temp.bak",
]

SHORT_CONTENTS = [
    "hello", "world", "test", "alpha", "bravo", "sample", "demo", "data",
    "value", "entry",
]

MULTI_WORD_CONTENTS = [
    "one two three four", "red green blue yellow", "alpha beta gamma delta",
    "north south east west", "spring summer autumn winter",
    "monday tuesday wednesday", "earth water fire air",
]

NUMBER_CONTENTS = [
    "10 20 5", "1 2 3 4 5", "100 200 300", "7 14 21 28",
    "9 8 7 6 5 4", "42 17 33 88", "3 1 4 1 5 9", "50 25 75 100",
]

SORTABLE_CONTENTS = [
    ("banana", "apple", "cherry"),
    ("zebra", "alpha", "mango"),
    ("python", "ada", "rust"),
    ("delta", "alpha", "charlie"),
]

LINE_CONTENTS = [
    ("first", "second", "third", "fourth"),
    ("alpha", "beta", "gamma", "delta"),
    ("north", "south", "east", "west"),
    ("red", "green", "blue", "yellow"),
]

LOG_CONTENTS = [
    ("error: disk full", "info: ok", "error: timeout"),
    ("warning: low memory", "error: crash", "info: startup"),
    ("debug: checkpoint", "error: null ptr", "warning: deprecated"),
    ("error: file missing", "info: retry", "error: permission denied"),
]

PATTERNS = ["error", "warning", "info", "debug"]

MOVE_DIRS = ["logs", "archive", "backup", "tmp", "store"]

HEAD_COUNTS = [1, 2, 3]


# ---------------------------------------------------------------------------
# Triple data structure
# ---------------------------------------------------------------------------

@dataclass
class Triple:
    """One execution-verified (intent, target_code, output) data point."""
    id: str
    intent: str               # the NL program
    asg_json: list            # serialized ASG nodes
    shell_code: str           # compiled shell script
    python_code: str          # compiled Python source
    expected_output: str      # what the program should produce
    node_types: list          # types of ASG nodes involved
    params: dict              # parameters used to generate this triple
    verified: bool            # all 3 backends produce expected_output


def serialize_asg(nodes: list[ASGNode]) -> list[dict]:
    """Serialize ASG nodes to JSON-safe dicts."""
    result = []
    for node in nodes:
        d = {"type": type(node).__name__}
        for field_name in node.__dataclass_fields__:
            if field_name == "node_type":
                continue
            val = getattr(node, field_name)
            if isinstance(val, list):
                # Sub-branches (Conditional.then_branch/else_branch)
                d[field_name] = serialize_asg(val)
            else:
                d[field_name] = val
        result.append(d)
    return result


# ---------------------------------------------------------------------------
# Template generators — each produces (program, expected_output, params_dict)
# ---------------------------------------------------------------------------

TemplateFn = Callable[[], list[tuple[str, str, dict]]]


def tpl_create_read() -> list[tuple[str, str, dict]]:
    out = []
    for fn, content in itertools.product(FILENAMES, SHORT_CONTENTS):
        prog = f'create file {fn} with content "{content}"\nread file {fn}'
        out.append((prog, content, {"template": "create-read", "filename": fn, "content": content}))
    return out


def tpl_append_read() -> list[tuple[str, str, dict]]:
    out = []
    for fn, base, extra in itertools.product(
        FILENAMES[:5], SHORT_CONTENTS[:5], SHORT_CONTENTS[5:]
    ):
        prog = f'create file {fn} with content "{base}"\nappend "{extra}" to {fn}\nread file {fn}'
        out.append((prog, f"{base} {extra}", {"template": "append-read", "filename": fn, "base": base, "extra": extra}))
    return out


def tpl_count_lines() -> list[tuple[str, str, dict]]:
    out = []
    for fn, base in itertools.product(FILENAMES[:5], SHORT_CONTENTS[:5]):
        prog = (
            f'create file {fn} with content "{base}"\n'
            f'append "line2" to {fn}\n'
            f'append "line3" to {fn}\n'
            f'count lines in {fn}'
        )
        out.append((prog, "3", {"template": "count-lines", "filename": fn, "base": base}))
    return out


def tpl_copy_read() -> list[tuple[str, str, dict]]:
    out = []
    for src, dest, content in itertools.product(
        FILENAMES[:4], FILENAMES[4:8], SHORT_CONTENTS[:6]
    ):
        prog = f'create file {src} with content "{content}"\ncopy {src} to {dest}\nread file {dest}'
        out.append((prog, content, {"template": "copy-read", "src": src, "dest": dest, "content": content}))
    return out


def tpl_mkdir_move_list() -> list[tuple[str, str, dict]]:
    out = []
    for fn, dirname, content in itertools.product(
        FILENAMES[:4], MOVE_DIRS, SHORT_CONTENTS[:4]
    ):
        prog = (
            f'create file {fn} with content "{content}"\n'
            f'make directory {dirname}\n'
            f'move {fn} to {dirname}\n'
            f'list files in {dirname}'
        )
        out.append((prog, fn, {"template": "mkdir-move-list", "filename": fn, "dir": dirname, "content": content}))
    return out


def tpl_list_files() -> list[tuple[str, str, dict]]:
    out = []
    for f1, f2 in itertools.product(FILENAMES[:5], FILENAMES[5:]):
        if f1 == f2:
            continue
        prog = f'create file {f1} with content "a"\ncreate file {f2} with content "b"\nlist files'
        expected = " ".join(sorted([f1, f2]))
        out.append((prog, expected, {"template": "list-files", "file1": f1, "file2": f2}))
    return out


def tpl_find_content() -> list[tuple[str, str, dict]]:
    out = []
    for needle in ["hello", "found", "target", "match"]:
        for fn_match, fn_miss in itertools.product(FILENAMES[:4], FILENAMES[4:8]):
            prog = (
                f'create file {fn_match} with content "{needle} here"\n'
                f'create file {fn_miss} with content "nothing here"\n'
                f'find files containing "{needle}"'
            )
            out.append((prog, fn_match, {"template": "find-content", "needle": needle, "match_file": fn_match, "miss_file": fn_miss}))
    return out


def tpl_count_words() -> list[tuple[str, str, dict]]:
    out = []
    for fn, content in itertools.product(FILENAMES[:5], MULTI_WORD_CONTENTS):
        prog = f'create file {fn} with content "{content}"\ncount words in {fn}'
        count = len(content.split())
        out.append((prog, str(count), {"template": "count-words", "filename": fn, "content": content}))
    return out


def tpl_sort_lines() -> list[tuple[str, str, dict]]:
    out = []
    for i, lines in enumerate(SORTABLE_CONTENTS):
        fn = FILENAMES[i % len(FILENAMES)]
        prog = (
            f'create file {fn} with content "{lines[0]}"\n'
            f'append "{lines[1]}" to {fn}\n'
            f'append "{lines[2]}" to {fn}\n'
            f'sort lines in {fn}'
        )
        expected = " ".join(sorted(lines))
        out.append((prog, expected, {"template": "sort-lines", "filename": fn, "lines": list(lines)}))
    return out


def tpl_head_lines() -> list[tuple[str, str, dict]]:
    out = []
    for i, lines in enumerate(LINE_CONTENTS):
        for n in HEAD_COUNTS:
            fn = FILENAMES[i % len(FILENAMES)]
            prog = (
                f'create file {fn} with content "{lines[0]}"\n'
                f'append "{lines[1]}" to {fn}\n'
                f'append "{lines[2]}" to {fn}\n'
                f'append "{lines[3]}" to {fn}\n'
                f'show first {n} lines of {fn}'
            )
            expected = " ".join(lines[:n])
            out.append((prog, expected, {"template": "head-lines", "filename": fn, "count": n, "lines": list(lines)}))
    return out


def tpl_sum_numbers() -> list[tuple[str, str, dict]]:
    out = []
    for fn, content in itertools.product(FILENAMES[:5], NUMBER_CONTENTS):
        prog = f'create file {fn} with content "{content}"\nsum numbers in {fn}'
        total = sum(int(x) for x in content.split())
        out.append((prog, str(total), {"template": "sum-numbers", "filename": fn, "content": content}))
    return out


def tpl_extract_pattern() -> list[tuple[str, str, dict]]:
    out = []
    for i, lines in enumerate(LOG_CONTENTS):
        for pattern in PATTERNS:
            fn = FILENAMES[i % len(FILENAMES)]
            prog = (
                f'create file {fn} with content "{lines[0]}"\n'
                f'append "{lines[1]}" to {fn}\n'
                f'append "{lines[2]}" to {fn}\n'
                f'extract lines matching "{pattern}" from {fn}'
            )
            matching = [l for l in lines if pattern in l]
            expected = " ".join(matching)
            out.append((prog, expected, {"template": "extract-pattern", "filename": fn, "pattern": pattern, "lines": list(lines)}))
    return out


def tpl_decision_else() -> list[tuple[str, str, dict]]:
    """Conditional: file doesn't exist → else branch creates it."""
    out = []
    for fn, content in itertools.product(FILENAMES[:5], SHORT_CONTENTS[:5]):
        missing = f"check_{fn}"
        prog = (
            f'if {missing} exists then read file {missing} otherwise '
            f'create file {fn} with content "{content}"\n'
            f'read file {fn}'
        )
        out.append((prog, content, {"template": "decision-else", "missing": missing, "filename": fn, "content": content}))
    return out


def tpl_safety_refuse_delete() -> list[tuple[str, str, dict]]:
    """Delete without confirm → REFUSED."""
    out = []
    for fn, content in itertools.product(FILENAMES[:5], SHORT_CONTENTS[:5]):
        prog = f'create file {fn} with content "{content}"\ndelete {fn}'
        out.append((prog, "REFUSED", {"template": "safety-refuse-delete", "filename": fn, "content": content}))
    return out


def tpl_safety_refuse_create() -> list[tuple[str, str, dict]]:
    """Create file that already exists → REFUSED."""
    out = []
    for fn, content in itertools.product(FILENAMES[:5], SHORT_CONTENTS[:5]):
        prog = (
            f'create file {fn} with content "{content}"\n'
            f'create file {fn} with content "overwrite"'
        )
        out.append((prog, "REFUSED", {"template": "safety-refuse-create", "filename": fn, "content": content}))
    return out


# Registry of all templates
TEMPLATES: list[tuple[str, TemplateFn]] = [
    ("create-read", tpl_create_read),
    ("append-read", tpl_append_read),
    ("count-lines", tpl_count_lines),
    ("copy-read", tpl_copy_read),
    ("mkdir-move-list", tpl_mkdir_move_list),
    ("list-files", tpl_list_files),
    ("find-content", tpl_find_content),
    ("count-words", tpl_count_words),
    ("sort-lines", tpl_sort_lines),
    ("head-lines", tpl_head_lines),
    ("sum-numbers", tpl_sum_numbers),
    ("extract-pattern", tpl_extract_pattern),
    ("decision-else", tpl_decision_else),
    ("safety-refuse-delete", tpl_safety_refuse_delete),
    ("safety-refuse-create", tpl_safety_refuse_create),
]


# ---------------------------------------------------------------------------
# Sandbox execution (mirrors test_v03.py)
# ---------------------------------------------------------------------------

def normalize(s: str) -> str:
    return " ".join(s.split())


def run_direct(program: str) -> str:
    """Run through the interpreter in a fresh sandbox."""
    work = Path(tempfile.mkdtemp(prefix="gen_direct_"))
    try:
        result = subprocess.run(
            [sys.executable, str(HERE / "_sandbox_run.py"), str(HERE / "interpreter.py")],
            input=program, capture_output=True, text=True,
            cwd=str(work), timeout=15,
        )
        return normalize(result.stdout.strip())
    finally:
        shutil.rmtree(work, ignore_errors=True)


def run_shell(script: str) -> str:
    work = Path(tempfile.mkdtemp(prefix="gen_sh_"))
    try:
        result = subprocess.run(
            ["sh"], input=script, capture_output=True, text=True,
            cwd=str(work), timeout=15,
        )
        return normalize(result.stdout.strip())
    finally:
        shutil.rmtree(work, ignore_errors=True)


def run_python(code: str) -> str:
    work = Path(tempfile.mkdtemp(prefix="gen_py_"))
    try:
        result = subprocess.run(
            [sys.executable, "-c", code],
            capture_output=True, text=True,
            cwd=str(work), timeout=15,
        )
        return normalize(result.stdout.strip())
    finally:
        shutil.rmtree(work, ignore_errors=True)


# ---------------------------------------------------------------------------
# Core: generate and verify a single triple
# ---------------------------------------------------------------------------

def verify_triple(program: str, expected: str) -> tuple[bool, dict]:
    """Execute program through all 3 backends, verify they match expected.

    Returns (verified, detail_dict).
    """
    nodes = parse(program)
    if not nodes:
        return False, {"error": "parse produced no nodes"}

    shell_code = compile_to_shell(nodes)
    python_code = compile_to_python(nodes)

    detail = {}

    # Direct execution
    try:
        direct_out = run_direct(program)
    except Exception as e:
        direct_out = f"<ERROR: {e}>"
    detail["direct"] = direct_out

    # Shell execution
    try:
        shell_out = run_shell(shell_code)
    except Exception as e:
        shell_out = f"<ERROR: {e}>"
    detail["shell"] = shell_out

    # Python execution
    try:
        python_out = run_python(python_code)
    except Exception as e:
        python_out = f"<ERROR: {e}>"
    detail["python"] = python_out

    verified = (
        direct_out == expected
        and shell_out == expected
        and python_out == expected
    )

    return verified, detail


# ---------------------------------------------------------------------------
# Main generation loop
# ---------------------------------------------------------------------------

def generate_all(target_count: int | None = None) -> list[Triple]:
    """Generate verified triples from all templates."""
    triples: list[Triple] = []
    counter = 0
    stats = {"total_generated": 0, "verified": 0, "failed": 0, "by_template": {}}

    for tpl_name, tpl_fn in TEMPLATES:
        instances = tpl_fn()
        tpl_verified = 0
        tpl_failed = 0

        for program, expected, params in instances:
            if target_count and len(triples) >= target_count:
                break

            counter += 1
            stats["total_generated"] += 1

            verified, detail = verify_triple(program, expected)

            nodes = parse(program)
            triple = Triple(
                id=f"{tpl_name}-{counter:04d}",
                intent=program,
                asg_json=serialize_asg(nodes),
                shell_code=compile_to_shell(nodes),
                python_code=compile_to_python(nodes),
                expected_output=expected,
                node_types=[type(n).__name__ for n in nodes],
                params=params,
                verified=verified,
            )
            triples.append(triple)

            if verified:
                tpl_verified += 1
                stats["verified"] += 1
            else:
                tpl_failed += 1
                stats["failed"] += 1
                # Print failures for debugging
                print(f"  ⚠️  FAIL {triple.id}: expected={expected!r} detail={detail}", file=sys.stderr)

        stats["by_template"][tpl_name] = {
            "generated": tpl_verified + tpl_failed,
            "verified": tpl_verified,
            "failed": tpl_failed,
        }

        if target_count and len(triples) >= target_count:
            break

    return triples


def export_jsonl(triples: list[Triple], path: Path) -> int:
    """Export verified triples to JSONL. Returns count of exported lines."""
    exported = 0
    with open(path, 'w') as f:
        for t in triples:
            if not t.verified:
                continue
            f.write(json.dumps(asdict(t)) + '\n')
            exported += 1
    return exported


def print_summary(triples: list[Triple], stats: dict):
    """Print generation summary statistics."""
    total = len(triples)
    verified = sum(1 for t in triples if t.verified)
    failed = total - verified

    print(f"\n{'='*60}")
    print(f"  Data Generation Pipeline — Summary")
    print(f"{'='*60}")
    print(f"  Total generated:  {total}")
    print(f"  Verified:         {verified}")
    print(f"  Failed (dropped): {failed}")
    print(f"  Pass rate:        {verified/total*100:.1f}%" if total else "  Pass rate: N/A")
    print()

    print(f"  {'Template':<25} {'Gen':>6} {'Pass':>6} {'Fail':>6} {'Rate':>7}")
    print(f"  {'-'*25} {'-'*6} {'-'*6} {'-'*6} {'-'*7}")
    for name, s in sorted(stats["by_template"].items()):
        rate = f"{s['verified']/s['generated']*100:.0f}%" if s['generated'] else "N/A"
        print(f"  {name:<25} {s['generated']:>6} {s['verified']:>6} {s['failed']:>6} {rate:>7}")

    # Node type distribution
    node_counts: dict[str, int] = {}
    for t in triples:
        if not t.verified:
            continue
        for nt in set(t.node_types):  # unique per triple
            node_counts[nt] = node_counts.get(nt, 0) + 1

    print(f"\n  Node type distribution (verified triples):")
    for nt, count in sorted(node_counts.items(), key=lambda x: -x[1]):
        print(f"    {nt:<20} {count:>4}")

    print(f"\n{'='*60}")


def main():
    parser = argparse.ArgumentParser(description="Generate execution-verified data triples")
    parser.add_argument("--out", default="triples.jsonl", help="Output JSONL path")
    parser.add_argument("--count", type=int, default=None, help="Target number of triples")
    parser.add_argument("--summary", action="store_true", help="Print stats only, don't write file")
    args = parser.parse_args()

    print("Generating triples...", file=sys.stderr)
    triples = generate_all(target_count=args.count)

    # Build stats
    stats = {"total_generated": len(triples), "verified": 0, "failed": 0, "by_template": {}}
    for t in triples:
        if t.verified:
            stats["verified"] += 1
        else:
            stats["failed"] += 1
    # Rebuild by_template from triples
    for t in triples:
        tn = t.params.get("template", "unknown")
        if tn not in stats["by_template"]:
            stats["by_template"][tn] = {"generated": 0, "verified": 0, "failed": 0}
        stats["by_template"][tn]["generated"] += 1
        if t.verified:
            stats["by_template"][tn]["verified"] += 1
        else:
            stats["by_template"][tn]["failed"] += 1

    print_summary(triples, stats)

    if not args.summary:
        out_path = Path(args.out)
        exported = export_jsonl(triples, out_path)
        print(f"\n  Exported {exported} verified triples → {out_path}", file=sys.stderr)
        size_kb = out_path.stat().st_size / 1024 if out_path.exists() else 0
        print(f"  File size: {size_kb:.1f} KB", file=sys.stderr)


if __name__ == "__main__":
    main()
