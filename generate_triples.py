#!/usr/bin/env python3
"""Execution-verified data generation pipeline.

Takes the conformance rungs from the ASG test suite, parameterizes them
(varying filenames, contents, patterns, numbers), executes each variant
through all backends, verifies the output matches, and exports the verified
triples as JSONL.

Each triple is a rejection-sampling data point:
  (intent, shell_command, python_code, sql_code, expected_output, verified=True)

Unverified triples are dropped (not emitted). This is the moat — the raw
material for model distillation.

Directory-dependent templates (mkdir-move-list) are verified through 3 backends
(direct, shell, python) since SQL has no directory hierarchy model.

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
from sql_backend import compile_to_sql, execute_sql


# ---------------------------------------------------------------------------
# Parameter pools — the variation axes (v3: massively scaled for 50K+ distillation)
# ---------------------------------------------------------------------------

FILENAMES = [
    # Original 10
    "notes.txt", "data.txt", "log.txt", "config.cfg", "output.dat",
    "report.md", "items.lst", "entries.log", "sample.txt", "temp.bak",
    # v2: extended — diverse extensions, multi-word names, edge-case names
    "main.py", "index.html", "styles.css", "app.js", "README.md",
    "todo.txt", "budget.csv", "events.json", "cache.tmp", "error.log",
    "alpha.dat", "beta.cfg", "gamma.txt", "delta.lst", "epsilon.md",
    "f1.dat", "f2.cfg", "f3.txt", "f4.lst", "f5.md",
    "test_a.txt", "test_b.txt", "test_c.dat", "test_d.cfg", "test_e.md",
    "names.csv", "ages.txt", "scores.dat", "paths.cfg", "flags.lst",
    # v3: extended — more diverse names for 50K+ scaling
    "users.db", "orders.csv", "inventory.lst", "config.yaml", "Makefile",
    "package.json", "Dockerfile", ".env", ".gitignore", "LICENSE",
    "a.txt", "b.txt", "c.txt", "d.txt", "e.txt",
    "x.dat", "y.dat", "z.dat", "w.dat", "v.dat",
    "doc1.txt", "doc2.txt", "doc3.txt", "doc4.txt", "doc5.txt",
    "run.sh", "build.sh", "deploy.sh", "test.sh", "clean.sh",
    "img1.dat", "img2.dat", "img3.dat", "img4.dat", "img5.dat",
    "log_a.txt", "log_b.txt", "log_c.txt", "log_d.txt", "log_e.txt",
    "file_001.txt", "file_002.txt", "file_003.txt", "file_004.txt", "file_005.txt",
]

SHORT_CONTENTS = [
    # Original 10
    "hello", "world", "test", "alpha", "bravo", "sample", "demo", "data",
    "value", "entry",
    # v2: extended
    "foo", "bar", "baz", "qux", "quux",
    "red", "green", "blue", "black", "white",
    "cat", "dog", "bird", "fish", "lion",
    "one", "two", "three", "four", "five",
    "start", "stop", "pause", "reset", "init",
    "true", "false", "null", "void", "empty",
    "404", "200", "301", "500", "403",
    "x", "y", "z", "id", "key",
    # v3: extended — more single-word content for 50K+ scaling
    "val", "num", "str", "buf", "ptr",
    "max", "min", "avg", "sum", "cnt",
    "row", "col", "cell", "line", "word",
    "yes", "no", "ok", "err", "nil",
    "abc", "def", "ghi", "jkl", "mno",
    "north", "south", "east", "west", "center",
    "open", "shut", "lock", "unlock", "seal",
    "fast", "slow", "high", "low", "mid",
    "big", "small", "huge", "tiny", "vast",
    "new", "old", "used", "free", "busy",
]

MULTI_WORD_CONTENTS = [
    # Original 7
    "one two three four", "red green blue yellow", "alpha beta gamma delta",
    "north south east west", "spring summer autumn winter",
    "monday tuesday wednesday", "earth water fire air",
    # v2: extended — varying lengths from 2 to 8 words
    "apple banana", "cat dog bird", "a b c d e",
    "foo bar baz qux quux", "1 2 3 4 5 6 7 8",
    "the quick brown fox jumps", "open close read write delete",
    "create update delete read execute",
    "tcp udp http https ftp",
    "monday wednesday friday sunday",
    "primary secondary tertiary quaternary",
    "inception inception inception dream",
    "red red red red red",
    "north 42 south 17 east 8",
    "name age email phone address",
    "start process end start process",
    # v3: extended — more multi-word content
    "error warning info debug trace",
    "create read update delete",
    "apple orange banana grape lemon",
    "python java rust go ruby",
    "insert select update delete drop",
    "header body footer sidebar nav",
    "january february march april",
    "add sub mul div mod",
    "earth mars venus mercury jupiter",
    "alpha bravo charlie delta echo",
    "red orange yellow green blue indigo violet",
    "north northeast east southeast south",
    "darwin linus alan grace ada",
    "bytes words longs shorts ints",
    "in out inout return break",
]

NUMBER_CONTENTS = [
    # Original 8
    "10 20 5", "1 2 3 4 5", "100 200 300", "7 14 21 28",
    "9 8 7 6 5 4", "42 17 33 88", "3 1 4 1 5 9", "50 25 75 100",
    # v2: extended
    "1", "0", "999",
    "1 1 1 1", "0 0 0 0 0",
    "100 200 300 400 500 600",
    "2 4 8 16 32 64 128",
    "1 3 5 7 9 11 13",
    "10 20 30 40 50",
    "5 10 15 20 25 30",
    "1000 100 10 1",
    "7 7 7 7 7 7 7",
    "1 2 4 8 16 32 64 128 256",
    "9 99 999 9999",
    "3 1 4 1 5 9 2 6 5",
    "12 34 56 78 90",
    "11 22 33 44 55 66 77 88",
    "500 250 125",
    "8 6 7 5 3 0 9",
    # v3: extended
    "15 30 45 60 75 90",
    "1000 2000 3000 4000",
    "3 6 9 12 15 18",
    "100 50 25 12 6 3",
    "2 3 5 7 11 13 17 19",
    "1 4 9 16 25 36 49 64",
    "10000 1000 100 10 1",
    "6 12 18 24 30 36",
    "20 40 60 80 100 120",
    "1 10 100 1000 10000",
    "64 32 16 8 4 2 1",
    "99 88 77 66 55 44",
    "1 1 2 3 5 8 13 21",
    "100 200 400 800 1600",
    "7 14 28 56 112 224",
    "42 42 42 42 42",
    "0 0 0 0",
]

SORTABLE_CONTENTS = [
    # Original 4
    ("banana", "apple", "cherry"),
    ("zebra", "alpha", "mango"),
    ("python", "ada", "rust"),
    ("delta", "alpha", "charlie"),
    # v2: extended — varying lengths and patterns
    ("mango", "apple", "banana", "cherry", "date"),
    ("zulu", "yankee", "xray", "whiskey", "victor"),
    ("red", "blue", "green", "yellow", "orange", "purple"),
    ("delta", "echo", "foxtrot", "golf", "hotel", "india"),
    ("cat", "ant", "bat", "dog", "eel"),
    ("nine", "eight", "seven", "six", "five", "four", "three"),
    ("zzz", "aaa", "mmm", "bbb"),
    ("ocean", "mountain", "river", "desert", "forest", "valley"),
    # v3: extended
    ("jupiter", "mars", "venus", "earth", "mercury", "saturn"),
    ("violet", "red", "indigo", "orange", "yellow", "green", "blue"),
    ("negative", "positive", "neutral", "active", "dormant"),
    ("whale", "dolphin", "shark", "tuna", "salmon"),
    ("jungle", "forest", "desert", "tundra", "savanna", "swamp"),
    ("numpy", "pandas", "scipy", "sklearn", "tensorflow"),
    ("quark", "atom", "molecule", "cell", "tissue", "organ"),
]

LINE_CONTENTS = [
    # Original 4
    ("first", "second", "third", "fourth"),
    ("alpha", "beta", "gamma", "delta"),
    ("north", "south", "east", "west"),
    ("red", "green", "blue", "yellow"),
    # v2: extended
    ("start", "middle", "end", "done"),
    ("one", "two", "three", "four", "five"),
    ("init", "load", "process", "save", "exit"),
    ("header", "body", "footer"),
    ("a", "b", "c", "d", "e", "f"),
    ("open", "close", "open", "close", "open"),
    ("error", "warn", "info", "debug", "trace"),
    ("100", "200", "300", "400"),
    ("alpha", "beta", "gamma"),
    ("line1", "line2", "line3", "line4", "line5", "line6"),
    ("x", "y", "z"),
    # v3: extended
    ("jan", "feb", "mar", "apr", "may", "jun"),
    ("sun", "mon", "tue", "wed", "thu", "fri", "sat"),
    ("create", "read", "update", "delete"),
    ("ping", "pong", "ping", "pong", "ping"),
    ("on", "off", "on", "off", "on", "off"),
    ("red", "green", "blue", "alpha", "beta"),
    ("tcp", "udp", "http", "https", "ftp", "ssh"),
    ("low", "medium", "high", "critical"),
    ("input", "process", "output", "feedback"),
    ("1", "2", "3", "4", "5", "6", "7", "8", "9", "10"),
    ("q1", "q2", "q3", "q4"),
    ("start", "run", "pause", "resume", "stop"),
    ("a1", "b2", "c3", "d4", "e5"),
    ("north", "south", "east", "west", "center"),
    ("login", "auth", "verify", "approve", "session"),
]

LOG_CONTENTS = [
    # Original 4 (3-line)
    ("error: disk full", "info: ok", "error: timeout"),
    ("warning: low memory", "error: crash", "info: startup"),
    ("debug: checkpoint", "error: null ptr", "warning: deprecated"),
    ("error: file missing", "info: retry", "error: permission denied"),
    # v2: extended — more patterns, more lines, mixed severities
    ("error: connection refused", "warning: slow response", "info: retrying"),
    ("debug: entered function", "error: segfault", "error: stack overflow"),
    ("info: server started", "warning: deprecated API", "error: port in use"),
    ("warning: certificate expiring", "info: health check passed", "error: timeout"),
    ("error: file not found", "error: permission denied", "warning: disk space low", "info: shutdown"),
    ("debug: var x=1", "debug: var y=2", "error: division by zero"),
    ("info: task queued", "info: task started", "error: task failed", "warning: retrying"),
    ("error: out of memory", "error: cpu limit", "warning: throttling", "info: recovered"),
    # v3: extended
    ("error: auth failed", "warning: retry login", "info: session expired"),
    ("debug: cache hit", "debug: cache miss", "info: response sent"),
    ("error: database locked", "warning: query slow", "error: deadlock detected"),
    ("info: backup started", "info: backup completed", "warning: backup stale"),
    ("error: network unreachable", "error: dns failed", "info: reconnecting"),
    ("warning: high cpu", "warning: high memory", "error: system overload"),
    ("debug: request received", "info: processing", "debug: response built", "info: response sent"),
    ("error: invalid token", "error: expired session", "warning: refresh needed"),
    ("info: deploy started", "info: build complete", "info: deploy finished", "error: smoke test failed"),
]

PATTERNS = [
    "error", "warning", "info", "debug", "task", "file", "port", "memory",
    # v3: extended
    "cache", "auth", "connection", "backup", "network", "system", "request", "deploy",
]

MOVE_DIRS = [
    "logs", "archive", "backup", "tmp", "store", "cache", "dist", "build",
    # v3: extended
    "old", "new", "src", "out", "pub", "dev", "prod", "staging",
]

HEAD_COUNTS = [1, 2, 3, 4, 5]
TAIL_COUNTS = [1, 2, 3, 4, 5]

# v3: New parameter pools for new templates

REPLACE_PAIRS = [
    ("foo", "bar"), ("error", "warning"), ("old", "new"), ("true", "false"),
    ("yes", "no"), ("on", "off"), ("open", "closed"), ("start", "stop"),
    ("red", "blue"), ("cat", "dog"), ("begin", "end"), ("add", "remove"),
    ("create", "destroy"), ("accept", "reject"), ("enable", "disable"),
    ("connect", "disconnect"), ("login", "logout"), ("encrypt", "decrypt"),
    ("positive", "negative"), ("active", "inactive"),
]

CASE_DIRECTIONS = ["uppercase", "lowercase"]


# ---------------------------------------------------------------------------
# Templates that cannot be verified through SQL (directory-dependent)
# ---------------------------------------------------------------------------

SQL_INCOMPATIBLE = {
    "mkdir-move-list",
    # v3: new node types not yet supported by SQL backend
    "tail-lines", "reverse-lines", "unique-lines",
    "transform-case", "replace-text",
}


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
    sql_code: str             # compiled SQL statements
    expected_output: str      # what the program should produce
    node_types: list          # types of ASG nodes involved
    params: dict              # parameters used to generate this triple
    verified: bool            # all applicable backends produce expected_output
    backends_verified: list   # which backends were checked


def serialize_asg(nodes: list[ASGNode]) -> list[dict]:
    """Serialize ASG nodes to JSON-compatible list."""
    return [{"type": type(n).__name__, **asdict(n)} for n in nodes]


# ---------------------------------------------------------------------------
# Template functions — each generates a set of NL programs with expected output
# ---------------------------------------------------------------------------

TemplateFn = Callable[[], list[tuple[str, str, dict]]]


def tpl_create_read() -> list[tuple[str, str, dict]]:
    out = []
    for fn, content in itertools.product(FILENAMES[:40], SHORT_CONTENTS[:60]):
        prog = f'create file {fn} with content "{content}"\nread file {fn}'
        out.append((prog, content, {"template": "create-read", "filename": fn, "content": content}))
    return out


def tpl_append_read() -> list[tuple[str, str, dict]]:
    out = []
    for fn, base, extra in itertools.product(
        FILENAMES[:15], SHORT_CONTENTS[:15], SHORT_CONTENTS[15:30]
    ):
        prog = f'create file {fn} with content "{base}"\nappend "{extra}" to {fn}\nread file {fn}'
        out.append((prog, f"{base} {extra}", {"template": "append-read", "filename": fn, "base": base, "extra": extra}))
    return out


def tpl_count_lines() -> list[tuple[str, str, dict]]:
    out = []
    for fn, base in itertools.product(FILENAMES[:25], SHORT_CONTENTS[:25]):
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
        FILENAMES[:15], FILENAMES[15:30], SHORT_CONTENTS[:20]
    ):
        prog = f'create file {src} with content "{content}"\ncopy {src} to {dest}\nread file {dest}'
        out.append((prog, content, {"template": "copy-read", "src": src, "dest": dest, "content": content}))
    return out


def tpl_mkdir_move_list() -> list[tuple[str, str, dict]]:
    out = []
    for fn, dirname, content in itertools.product(
        FILENAMES[:10], MOVE_DIRS, SHORT_CONTENTS[:8]
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
    for f1, f2 in itertools.product(FILENAMES[:15], FILENAMES[15:30]):
        if f1 == f2:
            continue
        prog = f'create file {f1} with content "a"\ncreate file {f2} with content "b"\nlist files'
        expected = " ".join(sorted([f1, f2]))
        out.append((prog, expected, {"template": "list-files", "file1": f1, "file2": f2}))
    return out


def tpl_find_content() -> list[tuple[str, str, dict]]:
    out = []
    for needle in ["hello", "found", "target", "match", "key", "error", "data", "debug"]:
        for fn_match, fn_miss in itertools.product(FILENAMES[:8], FILENAMES[8:16]):
            prog = (
                f'create file {fn_match} with content "{needle} here"\n'
                f'create file {fn_miss} with content "nothing here"\n'
                f'find files containing "{needle}"'
            )
            out.append((prog, fn_match, {"template": "find-content", "needle": needle, "match_file": fn_match, "miss_file": fn_miss}))
    return out


def tpl_count_words() -> list[tuple[str, str, dict]]:
    out = []
    for fn, content in itertools.product(FILENAMES[:25], MULTI_WORD_CONTENTS):
        prog = f'create file {fn} with content "{content}"\ncount words in {fn}'
        count = len(content.split())
        out.append((prog, str(count), {"template": "count-words", "filename": fn, "content": content}))
    return out


def tpl_sort_lines() -> list[tuple[str, str, dict]]:
    out = []
    for i, lines in enumerate(SORTABLE_CONTENTS):
        for fn in FILENAMES[:8]:
            prog_parts = [f'create file {fn} with content "{lines[0]}"']
            for extra in lines[1:]:
                prog_parts.append(f'append "{extra}" to {fn}')
            prog_parts.append(f'sort lines in {fn}')
            prog = "\n".join(prog_parts)
            expected = " ".join(sorted(lines))
            out.append((prog, expected, {"template": "sort-lines", "filename": fn, "lines": list(lines)}))
    return out


def tpl_head_lines() -> list[tuple[str, str, dict]]:
    out = []
    for i, lines in enumerate(LINE_CONTENTS):
        for n in HEAD_COUNTS:
            for fn in FILENAMES[:5]:
                if n > len(lines):
                    continue
                prog_parts = [f'create file {fn} with content "{lines[0]}"']
                for extra in lines[1:]:
                    prog_parts.append(f'append "{extra}" to {fn}')
                prog_parts.append(f'show first {n} lines of {fn}')
                prog = "\n".join(prog_parts)
                expected = " ".join(lines[:n])
                out.append((prog, expected, {"template": "head-lines", "filename": fn, "count": n, "lines": list(lines)}))
    return out


def tpl_sum_numbers() -> list[tuple[str, str, dict]]:
    out = []
    for fn, content in itertools.product(FILENAMES[:25], NUMBER_CONTENTS):
        prog = f'create file {fn} with content "{content}"\nsum numbers in {fn}'
        total = sum(int(x) for x in content.split())
        out.append((prog, str(total), {"template": "sum-numbers", "filename": fn, "content": content}))
    return out


def tpl_extract_pattern() -> list[tuple[str, str, dict]]:
    out = []
    for i, lines in enumerate(LOG_CONTENTS):
        for pattern in PATTERNS:
            for fn in FILENAMES[:5]:
                prog_parts = [f'create file {fn} with content "{lines[0]}"']
                for extra in lines[1:]:
                    prog_parts.append(f'append "{extra}" to {fn}')
                prog_parts.append(f'extract lines matching "{pattern}" from {fn}')
                prog = "\n".join(prog_parts)
                matching = [l for l in lines if pattern in l]
                expected = " ".join(matching)
                if not matching:
                    continue  # skip patterns that match nothing
                out.append((prog, expected, {"template": "extract-pattern", "filename": fn, "pattern": pattern, "lines": list(lines)}))
    return out


def tpl_decision_else() -> list[tuple[str, str, dict]]:
    """Conditional: file doesn't exist → else branch creates it."""
    out = []
    for fn, content in itertools.product(FILENAMES[:10], SHORT_CONTENTS[:10]):
        missing = f"check_{fn}"
        prog = (
            f'if {missing} exists then read file {missing} otherwise '
            f'create file {fn} with content "{content}"\n'
            f'read file {fn}'
        )
        out.append((prog, content, {"template": "decision-else", "missing": missing, "filename": fn, "content": content}))
    return out


def tpl_decision_then() -> list[tuple[str, str, dict]]:
    """Conditional: file exists → then branch reads it."""
    out = []
    for fn, content in itertools.product(FILENAMES[:10], SHORT_CONTENTS[:10]):
        prog = (
            f'create file {fn} with content "{content}"\n'
            f'if {fn} exists then read file {fn} otherwise create file backup.txt with content "empty"'
        )
        out.append((prog, content, {"template": "decision-then", "filename": fn, "content": content}))
    return out


def tpl_safety_refuse_delete() -> list[tuple[str, str, dict]]:
    """Delete without confirm → REFUSED."""
    out = []
    for fn, content in itertools.product(FILENAMES[:10], SHORT_CONTENTS[:10]):
        prog = f'create file {fn} with content "{content}"\ndelete {fn}'
        out.append((prog, "REFUSED", {"template": "safety-refuse-delete", "filename": fn, "content": content}))
    return out


def tpl_safety_refuse_create() -> list[tuple[str, str, dict]]:
    """Create file that already exists → REFUSED."""
    out = []
    for fn, content in itertools.product(FILENAMES[:10], SHORT_CONTENTS[:10]):
        prog = (
            f'create file {fn} with content "{content}"\n'
            f'create file {fn} with content "overwrite"'
        )
        out.append((prog, "REFUSED", {"template": "safety-refuse-create", "filename": fn, "content": content}))
    return out


def tpl_safety_confirm_delete() -> list[tuple[str, str, dict]]:
    """Delete with confirm → file removed (empty output)."""
    out = []
    for fn, content in itertools.product(FILENAMES[:8], SHORT_CONTENTS[:8]):
        prog = (
            f'create file {fn} with content "{content}"\n'
            f'delete {fn} confirm\n'
            f'list files'
        )
        out.append((prog, "(empty)", {"template": "safety-confirm-delete", "filename": fn, "content": content}))
    return out


# ---------------------------------------------------------------------------
# v3 NEW TEMPLATES — covering previously uncovered ASG node types
# ---------------------------------------------------------------------------

def tpl_tail_lines() -> list[tuple[str, str, dict]]:
    """TailLines: show last N lines of a file."""
    out = []
    for i, lines in enumerate(LINE_CONTENTS):
        for n in TAIL_COUNTS:
            for fn in FILENAMES[:5]:
                if n > len(lines):
                    continue
                prog_parts = [f'create file {fn} with content "{lines[0]}"']
                for extra in lines[1:]:
                    prog_parts.append(f'append "{extra}" to {fn}')
                prog_parts.append(f'show last {n} lines of {fn}')
                prog = "\n".join(prog_parts)
                expected = " ".join(lines[-n:])
                out.append((prog, expected, {"template": "tail-lines", "filename": fn, "count": n, "lines": list(lines)}))
    return out


def tpl_reverse_lines() -> list[tuple[str, str, dict]]:
    """ReverseLines: reverse the order of lines in a file."""
    out = []
    for i, lines in enumerate(LINE_CONTENTS):
        for fn in FILENAMES[:8]:
            prog_parts = [f'create file {fn} with content "{lines[0]}"']
            for extra in lines[1:]:
                prog_parts.append(f'append "{extra}" to {fn}')
            prog_parts.append(f'reverse lines in {fn}')
            prog = "\n".join(prog_parts)
            expected = " ".join(reversed(lines))
            out.append((prog, expected, {"template": "reverse-lines", "filename": fn, "lines": list(lines)}))
    return out


def tpl_unique_lines() -> list[tuple[str, str, dict]]:
    """UniqueLines: deduplicate lines in a file."""
    out = []
    # Use line sets with duplicates
    dup_line_sets = [
        ("a", "b", "a", "b", "a"),
        ("red", "blue", "red", "green", "blue"),
        ("1", "2", "1", "3", "2", "1"),
        ("x", "x", "y", "y", "z", "z"),
        ("cat", "dog", "cat", "bird", "dog", "fish"),
        ("on", "off", "on", "off", "on"),
        ("start", "stop", "start", "stop", "pause"),
        ("error", "warn", "error", "info", "warn"),
        ("create", "delete", "create", "update", "delete", "read"),
        ("north", "south", "east", "north", "west", "south"),
        ("apple", "apple", "apple", "banana", "apple"),
        ("1", "1", "1", "1", "1"),
        ("a", "b", "c", "c", "b", "a"),
        ("big", "small", "big", "big", "small"),
        ("sync", "async", "sync", "sync", "async", "async"),
    ]
    for i, lines in enumerate(dup_line_sets):
        for fn in FILENAMES[:5]:
            prog_parts = [f'create file {fn} with content "{lines[0]}"']
            for extra in lines[1:]:
                prog_parts.append(f'append "{extra}" to {fn}')
            prog_parts.append(f'unique lines in {fn}')
            prog = "\n".join(prog_parts)
            # Preserve order of first occurrence
            seen = []
            for l in lines:
                if l not in seen:
                    seen.append(l)
            expected = " ".join(seen)
            out.append((prog, expected, {"template": "unique-lines", "filename": fn, "lines": list(lines)}))
    return out


def tpl_transform_case() -> list[tuple[str, str, dict]]:
    """TransformCase: uppercase or lowercase file content."""
    out = []
    case_contents = [
        "hello world", "Hello World", "HELLO WORLD",
        "Mixed Case Text", "ALL CAPS HERE", "lower case only",
        "PyThOn", "camelCase", "PascalCase",
        "MiXeD CaSe HeRe", "some Words with CAPS",
        "test data here", "ERROR WARNING INFO",
        "alpha beta gamma", "The Quick Brown Fox",
    ]
    for fn, content in itertools.product(FILENAMES[:10], case_contents):
        # uppercase
        prog_up = f'create file {fn} with content "{content}"\nuppercase {fn}'
        out.append((prog_up, content.upper(), {"template": "transform-case", "direction": "upper", "filename": fn, "content": content}))
        # lowercase
        prog_lo = f'create file {fn} with content "{content}"\nlowercase {fn}'
        out.append((prog_lo, content.lower(), {"template": "transform-case", "direction": "lower", "filename": fn, "content": content}))
    return out


def tpl_replace_text() -> list[tuple[str, str, dict]]:
    """ReplaceText: replace all occurrences of a word in file content."""
    out = []
    for fn, (old, new) in itertools.product(FILENAMES[:15], REPLACE_PAIRS):
        content = f"the {old} is {old} again"
        prog = f'create file {fn} with content "{content}"\nreplace "{old}" with "{new}" in {fn}'
        expected = content.replace(old, new)
        out.append((prog, expected, {"template": "replace-text", "filename": fn, "old": old, "new": new, "content": content}))
    return out


# ---------------------------------------------------------------------------
# Registry of all templates
# ---------------------------------------------------------------------------

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
    ("decision-then", tpl_decision_then),
    ("safety-refuse-delete", tpl_safety_refuse_delete),
    ("safety-refuse-create", tpl_safety_refuse_create),
    ("safety-confirm-delete", tpl_safety_confirm_delete),
    # v3 new templates
    ("tail-lines", tpl_tail_lines),
    ("reverse-lines", tpl_reverse_lines),
    ("unique-lines", tpl_unique_lines),
    ("transform-case", tpl_transform_case),
    ("replace-text", tpl_replace_text),
]


# ---------------------------------------------------------------------------
# Sandbox execution
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


def run_sql(nodes: list[ASGNode]) -> str:
    """Run through the SQL backend (in-memory SQLite)."""
    try:
        return normalize(execute_sql(nodes).strip())
    except Exception as e:
        return f"<ERROR: {e}>"


def verify_triple(program: str, expected: str, template_name: str) -> tuple[bool, str, list[str]]:
    """Execute program through all backends and verify output matches.

    Returns (verified, detail, list_of_backends_verified).
    """
    expected_n = normalize(expected)
    backends_ok = []

    # Parse to ASG
    try:
        nodes = parse(program)
    except Exception as e:
        return False, f"parse error: {e}", []

    # Direct interpreter
    try:
        direct_out = run_direct(program)
        if direct_out != expected_n:
            return False, f"direct: got {direct_out!r} expected {expected_n!r}", backends_ok
        backends_ok.append("direct")
    except Exception as e:
        return False, f"direct exception: {e}", backends_ok

    # Shell backend
    try:
        shell_code = compile_to_shell(nodes)
        shell_out = run_shell(shell_code)
        if shell_out != expected_n:
            return False, f"shell: got {shell_out!r} expected {expected_n!r}", backends_ok
        backends_ok.append("shell")
    except Exception as e:
        return False, f"shell exception: {e}", backends_ok

    # Python backend
    try:
        python_code = compile_to_python(nodes)
        python_out = run_python(python_code)
        if python_out != expected_n:
            return False, f"python: got {python_out!r} expected {expected_n!r}", backends_ok
        backends_ok.append("python")
    except Exception as e:
        return False, f"python exception: {e}", backends_ok

    # SQL backend (skip for incompatible templates)
    if template_name not in SQL_INCOMPATIBLE:
        try:
            sql_out = run_sql(nodes)
            if sql_out != expected_n:
                return False, f"sql: got {sql_out!r} expected {expected_n!r}", backends_ok
            backends_ok.append("sql")
        except Exception as e:
            return False, f"sql exception: {e}", backends_ok

    return True, "OK", backends_ok


def generate_all(target_count: int | None = None) -> list[Triple]:
    """Generate all triples from all templates."""
    triples: list[Triple] = []
    stats: dict = {"total_generated": 0, "verified": 0, "failed": 0, "by_template": {}}

    for tpl_name, tpl_fn in TEMPLATES:
        instances = tpl_fn()
        tpl_verified = 0
        tpl_failed = 0
        counter = 0

        print(f"  Generating {tpl_name}... ({len(instances)} candidates)", file=sys.stderr)

        for program, expected, params in instances:
            if target_count and len(triples) >= target_count:
                break

            counter += 1
            stats["total_generated"] += 1

            verified, detail, backends = verify_triple(program, expected, tpl_name)

            nodes = parse(program)
            triple = Triple(
                id=f"{tpl_name}-{counter:04d}",
                intent=program,
                asg_json=serialize_asg(nodes),
                shell_code=compile_to_shell(nodes),
                python_code=compile_to_python(nodes),
                sql_code=compile_to_sql(nodes),
                expected_output=expected,
                node_types=[type(n).__name__ for n in nodes],
                params=params,
                verified=verified,
                backends_verified=backends,
            )
            triples.append(triple)

            if verified:
                tpl_verified += 1
                stats["verified"] += 1
            else:
                tpl_failed += 1
                stats["failed"] += 1
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

    node_counts: dict[str, int] = {}
    for t in triples:
        if not t.verified:
            continue
        for nt in set(t.node_types):
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

    stats = {"total_generated": len(triples), "verified": 0, "failed": 0, "by_template": {}}
    for t in triples:
        if t.verified:
            stats["verified"] += 1
        else:
            stats["failed"] += 1
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
