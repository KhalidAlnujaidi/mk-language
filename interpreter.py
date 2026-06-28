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

Output convention: each Terminal node emits its result followed by a newline,
so consecutive Terminal outputs are separated. Process/Decision nodes that emit
REFUSED also get a trailing newline.

v03.1: Added GlobFiles + ForEachFile execution.
"""

from __future__ import annotations

import fnmatch
import os
import sys
from dataclasses import replace as dc_replace
from typing import Any

import asg
from asg import (
    ASGNode, CreateFile, ReadFile, AppendFile, CountLines, CopyFile,
    MakeDirectory, MoveFile, ListFiles, FindFiles, DeleteFile, Conditional,
    CountWords, SortLines, HeadLines, SumNumbers, ExtractPattern,
    GlobFiles, ForEachFile,
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


def _emit_result(emit, value: str) -> None:
    """Emit a Terminal/Process result with trailing newline.

    This is the key fix: consecutive Terminal outputs are now separated.
    - "2" then "4" → "2\\n4\\n" instead of "24"
    - Empty results (e.g. from Process nodes that don't emit) produce nothing.
    """
    if value is not None and value != "":
        emit(value + "\n")


# ---------------------------------------------------------------------------
# Placeholder substitution for ForEachFile
# ---------------------------------------------------------------------------

def _substitute_placeholder(node: ASGNode, placeholder: str, filename: str) -> ASGNode:
    """Return a copy of node with {placeholder} replaced by filename in all
    string fields. Tuples/lists inside ForEachFile/Conditional are recursively substituted."""
    ph = placeholder

    match node:
        case CreateFile(name=name, content=content):
            return CreateFile(name=name.replace(ph, filename),
                              content=content.replace(ph, filename))

        case ReadFile(name=name):
            return ReadFile(name=name.replace(ph, filename))

        case AppendFile(text=text, name=name):
            return AppendFile(text=text.replace(ph, filename),
                              name=name.replace(ph, filename))

        case CountLines(name=name):
            return CountLines(name=name.replace(ph, filename))

        case CountWords(name=name):
            return CountWords(name=name.replace(ph, filename))

        case SortLines(name=name):
            return SortLines(name=name.replace(ph, filename))

        case HeadLines(name=name, count=count):
            return HeadLines(name=name.replace(ph, filename), count=count)

        case SumNumbers(name=name):
            return SumNumbers(name=name.replace(ph, filename))

        case ExtractPattern(name=name, pattern=pattern):
            return ExtractPattern(name=name.replace(ph, filename),
                                  pattern=pattern.replace(ph, filename))

        case CopyFile(source=source, dest=dest):
            return CopyFile(source=source.replace(ph, filename),
                            dest=dest.replace(ph, filename))

        case MakeDirectory(name=name):
            return MakeDirectory(name=name.replace(ph, filename))

        case MoveFile(source=source, dest=dest):
            return MoveFile(source=source.replace(ph, filename),
                            dest=dest.replace(ph, filename))

        case DeleteFile(name=name, confirm=confirm):
            return DeleteFile(name=name.replace(ph, filename), confirm=confirm)

        case GlobFiles(pattern=pattern):
            return node  # no substitution needed

        case ListFiles(directory=directory):
            return ListFiles(directory=directory.replace(ph, filename))

        case FindFiles(text=text):
            return FindFiles(text=text.replace(ph, filename))

        case Conditional(condition_file=condition_file,
                         then_branch=then_branch,
                         else_branch=else_branch):
            sub_then = [_substitute_placeholder(n, ph, filename) for n in then_branch]
            sub_else = [_substitute_placeholder(n, ph, filename) for n in else_branch]
            return Conditional(condition_file=condition_file.replace(ph, filename),
                               then_branch=sub_then,
                               else_branch=sub_else)

        case _:
            return node


def _execute_node(node: ASGNode, emit) -> None:
    """Execute a single ASG node."""
    match node:

        case CreateFile(name=name, content=content):
            if os.path.exists(name):
                _emit_result(emit, "REFUSED")
                return
            with open(name, 'w') as f:
                f.write(content)

        case ReadFile(name=name):
            if not os.path.exists(name):
                _emit_result(emit, "")
                return
            with open(name, 'r') as f:
                content = f.read()
            _emit_result(emit, content.replace('\n', ' '))

        case AppendFile(text=text, name=name):
            if not os.path.exists(name):
                _emit_result(emit, "REFUSED")
                return
            with open(name, 'a') as f:
                f.write('\n' + text)

        case CountLines(name=name):
            if not os.path.exists(name):
                _emit_result(emit, "0")
                return
            with open(name, 'r') as f:
                lines = f.readlines()
            _emit_result(emit, str(len(lines)))

        case CountWords(name=name):
            if not os.path.exists(name):
                _emit_result(emit, "0")
                return
            with open(name, 'r') as f:
                content = f.read()
            _emit_result(emit, str(len(content.split())))

        case SortLines(name=name):
            if not os.path.exists(name):
                _emit_result(emit, "")
                return
            with open(name, 'r') as f:
                lines = [l.rstrip('\n') for l in f.readlines() if l.strip()]
            _emit_result(emit, ' '.join(sorted(lines)))

        case HeadLines(name=name, count=count):
            if not os.path.exists(name):
                _emit_result(emit, "")
                return
            with open(name, 'r') as f:
                lines = [l.rstrip('\n') for l in f.readlines()]
            _emit_result(emit, ' '.join(lines[:count]))

        case SumNumbers(name=name):
            if not os.path.exists(name):
                _emit_result(emit, "0")
                return
            with open(name, 'r') as f:
                content = f.read()
            import re as _re
            numbers = [int(x) for x in _re.findall(r'\d+', content)]
            _emit_result(emit, str(sum(numbers)))

        case ExtractPattern(name=name, pattern=pattern):
            if not os.path.exists(name):
                _emit_result(emit, "")
                return
            with open(name, 'r') as f:
                lines = [l.rstrip('\n') for l in f.readlines() if l.strip()]
            matching = [l for l in lines if pattern in l]
            _emit_result(emit, ' '.join(matching))

        case CopyFile(source=source, dest=dest):
            if not os.path.exists(source) or os.path.exists(dest):
                _emit_result(emit, "REFUSED")
                return
            with open(source, 'r') as fs, open(dest, 'w') as fd:
                fd.write(fs.read())

        case MakeDirectory(name=name):
            if os.path.exists(name):
                _emit_result(emit, "REFUSED")
                return
            os.makedirs(name, exist_ok=False)

        case MoveFile(source=source, dest=dest):
            if not os.path.exists(source):
                _emit_result(emit, "REFUSED")
                return
            if os.path.isdir(dest):
                final_dest = os.path.join(dest, os.path.basename(source))
            else:
                final_dest = dest
            if os.path.exists(final_dest):
                _emit_result(emit, "REFUSED")
                return
            os.rename(source, final_dest)

        case ListFiles(directory=directory):
            if not os.path.isdir(directory):
                _emit_result(emit, "(empty)")
                return
            files = sorted(
                f for f in os.listdir(directory)
                if os.path.isfile(os.path.join(directory, f))
            )
            _emit_result(emit, ' '.join(files) if files else "(empty)")

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
            _emit_result(emit, ' '.join(sorted(matches)) if matches else "(none)")

        case DeleteFile(name=name, confirm=confirm):
            if not confirm:
                _emit_result(emit, "REFUSED")
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

        # --- v03.1: Iteration nodes ---

        case GlobFiles(pattern=pattern):
            """List files matching a glob pattern, sorted, space-joined."""
            files = sorted(
                f for f in os.listdir('.')
                if os.path.isfile(f) and fnmatch.fnmatch(f, pattern)
            )
            _emit_result(emit, ' '.join(files) if files else "(none)")

        case ForEachFile(glob_pattern=glob_pattern,
                         body_template=body_template,
                         placeholder=placeholder):
            """Iterate over files matching the glob, executing body for each."""
            files = sorted(
                f for f in os.listdir('.')
                if os.path.isfile(f) and fnmatch.fnmatch(f, glob_pattern)
            )
            for fname in files:
                for tmpl in body_template:
                    substituted = _substitute_placeholder(tmpl, placeholder, fname)
                    _execute_node(substituted, emit)

        case _:
            pass  # Unknown node type — silently skip


# ---------------------------------------------------------------------------
# Entry point — preserves the run(source) contract
# ---------------------------------------------------------------------------

def run(source: str) -> None:
    """Parse source into ASG and execute it. Output goes to stdout."""
    nodes = asg.parse(source)
    execute(nodes, sys.stdout)
