"""ASG — Abstract Syntax Graph for the MK language.

This is the target-independent intermediate layer:
  English intent → parse() → [ASG nodes] → any backend

Each node is a frozen dataclass with a known operation type and typed fields.
Decision nodes carry sub-graphs (then/else branches as node lists), making the
graph structure explicit and traversable.

The CoRE structured-intent unit maps cleanly:
  Name   → the dataclass type name (e.g. CreateFile)
  Type   → Process / Terminal / Decision (the .node_type field)
  Instruction → the dataclass fields (filename, content, etc.)
  Connection → implicit in list order; explicit in Decision.then/else branches
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Union


# ---------------------------------------------------------------------------
# Node type definitions
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class CreateFile:
    """Process — create a new file. Fails closed if file already exists."""
    name: str
    content: str
    node_type: str = "Process"


@dataclass(frozen=True)
class ReadFile:
    """Terminal — read file content, newlines → spaces."""
    name: str
    node_type: str = "Terminal"


@dataclass(frozen=True)
class AppendFile:
    """Process — append text to existing file. Fails closed if file missing."""
    text: str
    name: str
    node_type: str = "Process"


@dataclass(frozen=True)
class CountLines:
    """Terminal — count lines in a file."""
    name: str
    node_type: str = "Terminal"


@dataclass(frozen=True)
class CopyFile:
    """Process — copy file. Fails closed if src missing or dest exists."""
    source: str
    dest: str
    node_type: str = "Process"


@dataclass(frozen=True)
class MakeDirectory:
    """Process — create a directory. Fails closed if it already exists."""
    name: str
    node_type: str = "Process"


@dataclass(frozen=True)
class MoveFile:
    """Process — move file/dir. Fails closed if src missing or dest exists."""
    source: str
    dest: str
    node_type: str = "Process"


@dataclass(frozen=True)
class ListFiles:
    """Terminal — list files (not dirs) in a directory, sorted, space-joined."""
    directory: str  # '.' for current dir
    node_type: str = "Terminal"


@dataclass(frozen=True)
class FindFiles:
    """Terminal — find files in current dir containing text."""
    text: str
    node_type: str = "Terminal"


@dataclass(frozen=True)
class DeleteFile:
    """Process — delete a file. confirm=True required or fails closed."""
    name: str
    confirm: bool = False
    node_type: str = "Process"


@dataclass(frozen=True)
class Conditional:
    """Decision — if file exists, execute then_branch, else else_branch."""
    condition_file: str
    then_branch: list  # list of ASG nodes
    else_branch: list  # list of ASG nodes
    node_type: str = "Decision"


# --- v03 expansion: computational Terminal nodes ---

@dataclass(frozen=True)
class CountWords:
    """Terminal — count words in a file (whitespace-split)."""
    name: str
    node_type: str = "Terminal"


@dataclass(frozen=True)
class SortLines:
    """Terminal — sort lines alphabetically, output space-joined."""
    name: str
    node_type: str = "Terminal"


@dataclass(frozen=True)
class HeadLines:
    """Terminal — show first N lines of a file, output space-joined."""
    name: str
    count: int
    node_type: str = "Terminal"


@dataclass(frozen=True)
class SumNumbers:
    """Terminal — extract all integers from file, return their sum."""
    name: str
    node_type: str = "Terminal"


@dataclass(frozen=True)
class ExtractPattern:
    """Terminal — extract lines containing pattern, output space-joined."""
    name: str
    pattern: str
    node_type: str = "Terminal"


# Union type for type checking
ASGNode = Union[
    CreateFile, ReadFile, AppendFile, CountLines, CopyFile,
    MakeDirectory, MoveFile, ListFiles, FindFiles, DeleteFile, Conditional,
    CountWords, SortLines, HeadLines, SumNumbers, ExtractPattern,
]


# ---------------------------------------------------------------------------
# Parser — NL text → list of ASG nodes
# ---------------------------------------------------------------------------

def parse(source: str) -> list[ASGNode]:
    """Parse multi-line NL source into a list of ASG nodes.

    Empty lines and lines starting with ';' are skipped (comments).
    """
    nodes = []
    for line in source.splitlines():
        line = line.strip()
        if not line or line.startswith(';'):
            continue
        node = parse_line(line)
        if node is not None:
            nodes.append(node)
    return nodes


def parse_line(line: str) -> ASGNode | None:
    """Parse a single NL line into one ASG node. Returns None for unparseable."""

    # create file NAME with content "TEXT"
    if m := re.match(r'create file (\S+) with content "([^"]*)"', line):
        return CreateFile(name=m.group(1), content=m.group(2))

    # read file NAME
    if m := re.match(r'read file (\S+)', line):
        return ReadFile(name=m.group(1))

    # append "TEXT" to NAME
    if m := re.match(r'append "([^"]*)" to (\S+)', line):
        return AppendFile(text=m.group(1), name=m.group(2))

    # count lines in NAME
    if m := re.match(r'count lines in (\S+)', line):
        return CountLines(name=m.group(1))

    # count words in NAME
    if m := re.match(r'count words in (\S+)', line):
        return CountWords(name=m.group(1))

    # sort lines in NAME
    if m := re.match(r'sort lines in (\S+)', line):
        return SortLines(name=m.group(1))

    # show first N lines of NAME
    if m := re.match(r'show first (\d+) lines of (\S+)', line):
        return HeadLines(name=m.group(2), count=int(m.group(1)))

    # sum numbers in NAME
    if m := re.match(r'sum numbers in (\S+)', line):
        return SumNumbers(name=m.group(1))

    # extract lines matching "PATTERN" from NAME
    if m := re.match(r'extract lines matching "([^"]*)" from (\S+)', line):
        return ExtractPattern(name=m.group(2), pattern=m.group(1))

    # copy SRC to DEST
    if m := re.match(r'copy (\S+) to (\S+)', line):
        return CopyFile(source=m.group(1), dest=m.group(2))

    # make directory NAME
    if m := re.match(r'make directory (\S+)', line):
        return MakeDirectory(name=m.group(1))

    # move SRC to DEST
    if m := re.match(r'move (\S+) to (\S+)', line):
        return MoveFile(source=m.group(1), dest=m.group(2))

    # list files (bare) or list files in DIR
    if m := re.match(r'list files(?:\s+in\s+(\S+))?\s*$', line):
        directory = m.group(1) if m.group(1) else '.'
        return ListFiles(directory=directory)

    # find files containing "TEXT"
    if m := re.match(r'find files containing "([^"]*)"', line):
        return FindFiles(text=m.group(1))

    # delete NAME confirm  (check this BEFORE bare delete)
    if m := re.match(r'delete (\S+) confirm\s*$', line):
        return DeleteFile(name=m.group(1), confirm=True)

    # delete NAME (without confirm)
    if m := re.match(r'delete (\S+)\s*$', line):
        return DeleteFile(name=m.group(1), confirm=False)

    # if NAME exists then INTENT otherwise INTENT
    if m := re.match(r'if (\S+) exists then (.+) otherwise (.+)', line):
        then_node = parse_line(m.group(2).strip())
        else_node = parse_line(m.group(3).strip())
        return Conditional(
            condition_file=m.group(1),
            then_branch=[then_node] if then_node else [],
            else_branch=[else_node] if else_node else [],
        )

    return None
