"""MK v03 interpreter — ASG-based execution engine.

Architecture:  source → asg.parse() → asg.execute() → stdout

This replaces v02's flat line-by-line approach with a proper graph:
  1. parse: NL text → list of ASG nodes (target-independent)
  2. execute: walk the ASG, perform OS ops, collect output

The run(source) contract is preserved for _sandbox_run.py backward compatibility.

Safety model (unchanged from v02 — fail-CLOSED on all irreversible ops):
  - CreateFile when file exists       → REFUSED
  - AppendFile when file missing      → REFUSED
  - CopyFile when src missing/dest exists → REFUSED
  - MakeDirectory when exists         → REFUSED
  - MoveFile when src missing/dest exists → REFUSED
  - DeleteFile without confirm        → REFUSED
"""

from __future__ import annotations

import os
import sys
from typing import Any

import asg
from asg import (
    ASGNode, CreateFile, ReadFile, AppendFile, CountLines, CopyFile,
    MakeDirectory, MoveFile, ListFiles, FindFiles, DeleteFile, Conditional,
    CountWords, SortLines, HeadLines, SumNumbers, ExtractPattern,
)


# ---------------------------------------------------------------------------
# Executor — walk the ASG and produce OS effects + output
# ---------------------------------------------------------------------------

def execute(nodes: list[ASGNode], out=None) -> str:
    """Execute a list of ASG nodes, collecting output.

    Writes to `out` (a writable stream) if provided, else to a buffer.
    Returns the full output string.
    """
    if out is None:
        buf = []
        _execute_nodes(nodes, buf.append)
        return ''.join(buf)
    else:
        _execute_nodes(nodes, out.write)
        return ''  # caller reads from out


def _execute_nodes(nodes: list[ASGNode], emit) -> None:
    """Execute nodes sequentially, calling emit(chunk) for output."""
    for node in nodes:
        _execute_node(node, emit)


def _execute_node(node: ASGNode, emit) -> None:
    """Execute a single ASG node."""
    match node:

        case CreateFile(name=name, content=content):
            if os.path.exists(name):
                emit("REFUSED")
                return
            with open(name, 'w') as f:
                f.write(content)

        case ReadFile(name=name):
            if not os.path.exists(name):
                emit("")
                return
            with open(name, 'r') as f:
                content = f.read()
            emit(content.replace('\n', ' '))

        case AppendFile(text=text, name=name):
            if not os.path.exists(name):
                emit("REFUSED")
                return
            with open(name, 'a') as f:
                f.write('\n' + text)

        case CountLines(name=name):
            if not os.path.exists(name):
                emit("0")
                return
            with open(name, 'r') as f:
                lines = f.readlines()
            emit(str(len(lines)))

        case CountWords(name=name):
            if not os.path.exists(name):
                emit("0")
                return
            with open(name, 'r') as f:
                content = f.read()
            emit(str(len(content.split())))

        case SortLines(name=name):
            if not os.path.exists(name):
                emit("")
                return
            with open(name, 'r') as f:
                lines = [l.rstrip('\n') for l in f.readlines() if l.strip()]
            emit(' '.join(sorted(lines)))

        case HeadLines(name=name, count=count):
            if not os.path.exists(name):
                emit("")
                return
            with open(name, 'r') as f:
                lines = [l.rstrip('\n') for l in f.readlines()]
            emit(' '.join(lines[:count]))

        case SumNumbers(name=name):
            if not os.path.exists(name):
                emit("0")
                return
            with open(name, 'r') as f:
                content = f.read()
            import re as _re
            numbers = [int(x) for x in _re.findall(r'\d+', content)]
            emit(str(sum(numbers)))

        case ExtractPattern(name=name, pattern=pattern):
            if not os.path.exists(name):
                emit("")
                return
            with open(name, 'r') as f:
                lines = [l.rstrip('\n') for l in f.readlines() if l.strip()]
            matching = [l for l in lines if pattern in l]
            emit(' '.join(matching))

        case CopyFile(source=source, dest=dest):
            if not os.path.exists(source) or os.path.exists(dest):
                emit("REFUSED")
                return
            with open(source, 'r') as fs, open(dest, 'w') as fd:
                fd.write(fs.read())

        case MakeDirectory(name=name):
            if os.path.exists(name):
                emit("REFUSED")
                return
            os.makedirs(name, exist_ok=False)

        case MoveFile(source=source, dest=dest):
            if not os.path.exists(source):
                emit("REFUSED")
                return
            if os.path.isdir(dest):
                final_dest = os.path.join(dest, os.path.basename(source))
            else:
                final_dest = dest
            if os.path.exists(final_dest):
                emit("REFUSED")
                return
            os.rename(source, final_dest)

        case ListFiles(directory=directory):
            if not os.path.isdir(directory):
                emit("(empty)")
                return
            files = sorted(
                f for f in os.listdir(directory)
                if os.path.isfile(os.path.join(directory, f))
            )
            emit(' '.join(files) if files else "(empty)")

        case FindFiles(text=text):
            matches = []
            for fname in os.listdir('.'):
                if not os.path.isfile(fname):
                    continue
                try:
                    with open(fname, 'r') as f:
                        if text in f.read():
                            matches.append(fname)
                except (OSError, UnicodeDecodeError):
                    continue
            emit(' '.join(sorted(matches)) if matches else "(none)")

        case DeleteFile(name=name, confirm=confirm):
            if not confirm:
                emit("REFUSED")
                return
            if os.path.isfile(name):
                os.remove(name)

        case Conditional(condition_file=condition_file,
                         then_branch=then_branch,
                         else_branch=else_branch):
            if os.path.exists(condition_file):
                _execute_nodes(then_branch, emit)
            else:
                _execute_nodes(else_branch, emit)

        case _:
            pass  # Unknown node type — silently skip


# ---------------------------------------------------------------------------
# Entry point — preserves the run(source) contract
# ---------------------------------------------------------------------------

def run(source: str) -> None:
    """Parse source into ASG and execute it. Output goes to stdout."""
    nodes = asg.parse(source)
    execute(nodes, out=sys.stdout)
    return None  # _sandbox_run.py checks for None → uses stdout buffer
