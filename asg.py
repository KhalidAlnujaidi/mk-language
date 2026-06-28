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

v03.1: Added GlobFiles + ForEachFile for iteration support.
v03.2: Added SetVar + PrintVar for variable binding (data-dependent workflows).
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


# --- v03.1: Iteration nodes ---

@dataclass(frozen=True)
class GlobFiles:
    """Terminal — list files matching a glob pattern (e.g. '*.txt'), sorted.

    Returns space-joined filenames. This is the iteration source.
    The pattern uses shell-style globbing: *, ?, character classes not supported.
    Only simple suffix patterns like '*.txt' or prefix patterns like 'data.*'.
    """
    pattern: str
    node_type: str = "Terminal"


@dataclass(frozen=True)
class ForEachFile:
    """Decision — iterate over files, executing body for each match.

    The body is a list of ASG nodes where the placeholder NAME is replaced
    with each matched filename at execution time.

    body_template: list of ASG nodes (frozen, so stored as a tuple)
    placeholder: the string in body node fields that gets substituted (e.g. '{file}')
    """
    glob_pattern: str          # pattern for GlobFiles
    body_template: tuple       # tuple of ASG nodes
    placeholder: str           # what to replace in body fields (default '{file}')
    node_type: str = "Decision"  # Decision because it contains branches


# --- v03.2: Variable binding nodes ---

@dataclass(frozen=True)
class SetVar:
    """Decision — execute source_node, capture its Terminal output into var_name.

    The source_node is executed normally; its output is captured (stripped of
    trailing newline) and stored in the interpreter's variable dict under var_name.

    Subsequent nodes whose string fields contain {var_name} will have the
    placeholder replaced with the captured value at execution time.
    """
    var_name: str
    source_node: ASGNode  # the node to execute and capture output from
    node_type: str = "Decision"


@dataclass(frozen=True)
class PrintVar:
    """Terminal — emit the value of a previously-set variable.

    If the variable hasn't been set, emits empty string (fail-soft).
    """
    var_name: str
    node_type: str = "Terminal"



# --- v03.3: Text transformation nodes ---

@dataclass(frozen=True)
class ReplaceText:
    """Terminal — replace all occurrences of old with new in file content."""
    name: str
    old: str
    new: str
    node_type: str = "Terminal"


@dataclass(frozen=True)
class TransformCase:
    """Terminal — transform text to upper/lower/title case."""
    name: str
    mode: str  # "upper", "lower", "title"
    node_type: str = "Terminal"


@dataclass(frozen=True)
class UniqueLines:
    """Terminal — remove duplicate lines, preserving first occurrence order."""
    name: str
    node_type: str = "Terminal"


@dataclass(frozen=True)
class ReverseLines:
    """Terminal — reverse the order of lines in a file."""
    name: str
    node_type: str = "Terminal"


# Union type for type checking
ASGNode = Union[
    CreateFile, ReadFile, AppendFile, CountLines, CopyFile,
    MakeDirectory, MoveFile, ListFiles, FindFiles, DeleteFile, Conditional,
    CountWords, SortLines, HeadLines, SumNumbers, ExtractPattern,
    GlobFiles, ForEachFile,
    SetVar, PrintVar,
    ReplaceText, TransformCase, UniqueLines, ReverseLines,
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

    # --- v03.2: Variable binding syntax ---

    # set VAR = count lines in NAME
    if m := re.match(r'set (\w+) = (.+)', line):
        var_name = m.group(1)
        inner = parse_line(m.group(2).strip())
        if inner is not None:
            return SetVar(var_name=var_name, source_node=inner)

    # print VAR  (or: show VAR, echo VAR)
    if m := re.match(r'(?:print|show|echo) \$(\w+)', line):
        return PrintVar(var_name=m.group(1))

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

    # delete NAME confirm
    if m := re.match(r'delete (\S+) confirm', line):
        return DeleteFile(name=m.group(1), confirm=True)

    # delete NAME (no confirm — will fail closed)
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


    # --- v03.3: Text transformation patterns ---

    # replace "OLD" with "NEW" in NAME
    if m := re.match(r'replace "([^"]*)" with "([^"]*)" in (\S+)', line):
        return ReplaceText(name=m.group(3), old=m.group(1), new=m.group(2))

    # uppercase NAME / lowercase NAME / titlecase NAME
    if m := re.match(r'(uppercase|lowercase|titlecase) (\S+)', line):
        mode_map = {"uppercase": "upper", "lowercase": "lower", "titlecase": "title"}
        return TransformCase(name=m.group(2), mode=mode_map[m.group(1)])

    # unique lines in NAME
    if m := re.match(r'unique lines in (\S+)', line):
        return UniqueLines(name=m.group(1))

    # reverse lines in NAME
    if m := re.match(r'reverse lines in (\S+)', line):
        return ReverseLines(name=m.group(1))

    # glob files matching "PATTERN"
    # glob files matching "PATTERN"
    if m := re.match(r'glob files matching "([^"]*)"', line):
        return GlobFiles(pattern=m.group(1))

    return None
