"""Terminal backend — compile ASG nodes to a shell script.

ASG → shell commands. Each node maps to a deterministic shell fragment.
The generated script, when run in a sandbox, produces the same OS outcome
as direct execution through the interpreter.

Safety model (fail-CLOSED — matches interpreter semantics):
  - Shell fragments guard with [ -e ] / [ -f ] checks before acting.
  - Irreversible ops without confirmation emit "REFUSED".

Key nuances (learned from v02's plateau):
  - count_lines: must count lines including the last line without a trailing
    newline. `wc -l` counts newlines (undercounts by 1). Use `awk 'END{print NR}'`.
  - list_files: filters to files only (not dirs), sorted, space-joined.
  - read_file: replaces newlines with spaces (matches interpreter semantics).
  - create_file: guards against overwrite (refuses if file exists).

v03.1: Added GlobFiles + ForEachFile compilation (shell for-loop).
v03.2: Added SetVar + PrintVar compilation (shell variable capture/emit).
"""

from __future__ import annotations

import shlex
from typing import Any

from asg import (
    ASGNode, CreateFile, ReadFile, AppendFile, CountLines, CopyFile,
    MakeDirectory, MoveFile, ListFiles, FindFiles, DeleteFile, Conditional,
    CountWords, SortLines, HeadLines, SumNumbers, ExtractPattern,
    GlobFiles, ForEachFile,
    SetVar, PrintVar,
)


def compile_to_shell(nodes: list[ASGNode]) -> str:
    """Compile a list of ASG nodes into a shell script string."""
    lines = ["#!/bin/sh", "set -e"]
    for node in nodes:
        compiled = _compile_node(node)
        lines.append(compiled)
    return '\n'.join(lines)


def _compile_node(node: ASGNode) -> str:
    """Compile a single ASG node to its shell equivalent."""

    match node:

        # --- v03.2: Variable binding ---

        case SetVar(var_name=var_name, source_node=source_node):
            # Capture output of source_node into a shell variable.
            # We compile the source node, then use command substitution $(...).
            shell_var = f"_mk_var_{var_name}"
            inner_code = _compile_node(source_node)
            # Wrap the inner code in $() for capture
            return f'{shell_var}=$(\n{inner_code}\n)'

        case PrintVar(var_name=var_name):
            shell_var = f"$_mk_var_{var_name}"
            return f'printf "%s" "{shell_var}"'

        case CreateFile(name=name, content=content):
            # Fail-closed: refuse if file already exists
            qcontent = shlex.quote(content)
            qname = shlex.quote(name)
            return (
                f'if [ -e {qname} ]; then\n'
                f'    printf "%s" "REFUSED"\n'
                f'else\n'
                f'    printf "%s" {qcontent} > {qname}\n'
                f'fi'
            )

        case ReadFile(name=name):
            qname = shlex.quote(name)
            return (
                f'if [ -f {qname} ]; then\n'
                f'    tr "\\n" " " < {qname}\n'
                f'fi'
            )

        case AppendFile(text=text, name=name):
            qtext = shlex.quote(text)
            qname = shlex.quote(name)
            return (
                f'if [ -f {qname} ]; then\n'
                f'    printf "\\n%s" {qtext} >> {qname}\n'
                f'else\n'
                f'    printf "%s" "REFUSED"\n'
                f'fi'
            )

        case CountLines(name=name):
            qname = shlex.quote(name)
            return (
                f'if [ -f {qname} ]; then\n'
                f'    awk \'END {{print NR}}\' {qname}\n'
                f'else\n'
                f'    printf "%s" "0"\n'
                f'fi'
            )

        case CountWords(name=name):
            qname = shlex.quote(name)
            return (
                f'if [ -f {qname} ]; then\n'
                f'    wc -w < {qname}\n'
                f'else\n'
                f'    printf "%s" "0"\n'
                f'fi'
            )

        case SortLines(name=name):
            qname = shlex.quote(name)
            return (
                f'if [ -f {qname} ]; then\n'
                f'    sort {qname} | tr "\\n" " "\n'
                f'else\n'
                f'    printf "%s" ""\n'
                f'fi'
            )

        case HeadLines(name=name, count=count):
            qname = shlex.quote(name)
            return (
                f'if [ -f {qname} ]; then\n'
                f'    head -n {count} {qname} | tr "\\n" " "\n'
                f'else\n'
                f'    printf "%s" ""\n'
                f'fi'
            )

        case SumNumbers(name=name):
            qname = shlex.quote(name)
            # Extract all integers and sum them
            return (
                f'if [ -f {qname} ]; then\n'
                f'    grep -oE \'[0-9]+\' {qname} | awk \'{{s+=$1}} END {{print s+0}}\'\n'
                f'else\n'
                f'    printf "%s" "0"\n'
                f'fi'
            )

        case ExtractPattern(name=name, pattern=pattern):
            qname = shlex.quote(name)
            qpat = shlex.quote(pattern)
            return (
                f'if [ -f {qname} ]; then\n'
                f'    grep {qpat} {qname} | tr "\\n" " "\n'
                f'else\n'
                f'    printf "%s" ""\n'
                f'fi'
            )

        case CopyFile(source=source, dest=dest):
            qsrc = shlex.quote(source)
            qdest = shlex.quote(dest)
            return (
                f'if [ ! -e {qsrc} ] || [ -e {qdest} ]; then\n'
                f'    printf "%s" "REFUSED"\n'
                f'else\n'
                f'    cp {qsrc} {qdest}\n'
                f'fi'
            )

        case MakeDirectory(name=name):
            qname = shlex.quote(name)
            return (
                f'if [ -e {qname} ]; then\n'
                f'    printf "%s" "REFUSED"\n'
                f'else\n'
                f'    mkdir {qname}\n'
                f'fi'
            )

        case MoveFile(source=source, dest=dest):
            qsrc = shlex.quote(source)
            qdest = shlex.quote(dest)
            basename = source.split('/')[-1] if '/' in source else source
            qbase = shlex.quote(basename)
            # Must handle directory destinations like the interpreter:
            # if dest is a dir, final = dest/basename(src)
            return (
                f'if [ ! -e {qsrc} ]; then\n'
                f'    printf "%s" "REFUSED"\n'
                f'elif [ -d {qdest} ]; then\n'
                f'    if [ -e {qdest}/{qbase} ]; then\n'
                f'        printf "%s" "REFUSED"\n'
                f'    else\n'
                f'        mv {qsrc} {qdest}\n'
                f'    fi\n'
                f'elif [ -e {qdest} ]; then\n'
                f'    printf "%s" "REFUSED"\n'
                f'else\n'
                f'    mv {qsrc} {qdest}\n'
                f'fi'
            )

        case ListFiles(directory=directory):
            qdir = shlex.quote(directory)
            if directory == '.':
                # List files in current dir
                return (
                    'files=""\n'
                    'for f in *; do\n'
                    '    [ -f "$f" ] && files="$files $f"\n'
                    'done\n'
                    'files=$(echo "$files" | xargs -n1 2>/dev/null | sort | tr "\\n" " " | sed \'s/ $//\')\n'
                    'if [ -z "$files" ]; then\n'
                    '    printf "%s" "(empty)"\n'
                    'else\n'
                    '    printf "%s" "$files"\n'
                    'fi'
                )
            else:
                return (
                    f'if [ -d {qdir} ]; then\n'
                    f'    files=""\n'
                    f'    for f in {qdir}/*; do\n'
                    f'        [ -f "$f" ] && files="$files $(basename "$f")"\n'
                    f'    done\n'
                    f'    files=$(echo "$files" | xargs -n1 2>/dev/null | sort | tr "\\n" " " | sed \'s/ $//\')\n'
                    f'    if [ -z "$files" ]; then\n'
                    f'        printf "%s" "(empty)"\n'
                    f'    else\n'
                    f'        printf "%s" "$files"\n'
                    f'    fi\n'
                    f'else\n'
                    f'    printf "%s" "(empty)"\n'
                    f'fi'
                )

        case FindFiles(text=text):
            qtext = shlex.quote(text)
            return (
                'matches=""\n'
                'for f in *; do\n'
                f'    if [ -f "$f" ] && grep -q {qtext} "$f"; then\n'
                '        matches="$matches $f"\n'
                '    fi\n'
                'done\n'
                'matches=$(echo "$matches" | xargs -n1 2>/dev/null | sort | tr "\\n" " " | sed \'s/ $//\')\n'
                'if [ -z "$matches" ]; then\n'
                '    printf "%s" "(none)"\n'
                'else\n'
                '    printf "%s" "$matches"\n'
                'fi'
            )

        case DeleteFile(name=name, confirm=confirm):
            qname = shlex.quote(name)
            if not confirm:
                return f'printf "%s" "REFUSED"'
            return (
                f'if [ -f {qname} ]; then\n'
                f'    rm {qname}\n'
                f'fi'
            )

        case Conditional(condition_file=condition_file,
                         then_branch=then_branch,
                         else_branch=else_branch):
            qcond = shlex.quote(condition_file)
            then_code = '\n'.join('    ' + _compile_node(n) for n in then_branch)
            else_code = '\n'.join('    ' + _compile_node(n) for n in else_branch)
            return (
                f'if [ -e {qcond} ]; then\n'
                f'{then_code}\n'
                f'else\n'
                f'{else_code}\n'
                f'fi'
            )

        # --- v03.1: Iteration nodes ---

        case GlobFiles(pattern=pattern):
            qpat = shlex.quote(pattern)
            return (
                f'_mk_glob=""\n'
                f'for _mk_f in {qpat}; do\n'
                f'    [ -f "$_mk_f" ] && _mk_glob="$_mk_glob $_mk_f"\n'
                f'done\n'
                f'_mk_glob=$(echo "$_mk_glob" | xargs -n1 2>/dev/null | sort | tr "\\n" " " | sed \'s/ $//\')\n'
                f'if [ -z "$_mk_glob" ]; then\n'
                f'    printf "%s" "(none)"\n'
                f'else\n'
                f'    printf "%s" "$_mk_glob"\n'
                f'fi'
            )

        case ForEachFile(glob_pattern=glob_pattern,
                         body_template=body_template,
                         placeholder=placeholder):
            qpat = shlex.quote(glob_pattern)
            lines = [
                f'for _mk_f in {qpat}; do',
                f'    [ -f "$_mk_f" ] || continue',
            ]
            for tmpl in body_template:
                shell_code = _compile_node(tmpl)
                shell_code = shell_code.replace(placeholder, '$_mk_f')
                for code_line in shell_code.split('\n'):
                    lines.append(f'    {code_line}')
            lines.append('done')
            return '\n'.join(lines)

        case _:
            return '# unknown node type'
