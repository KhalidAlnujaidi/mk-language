#!/usr/bin/env python3
"""Run all 11 conformance tests against the interpreter via the sandbox runner.
Reports pass/fail per capability and overall score."""
from __future__ import annotations
import os, shutil, subprocess, sys, tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
INTERP = HERE / "interpreter.py"
SANDBOX = HERE / "_sandbox_run.py"
PYTHON = sys.executable

CONFORMANCE = (
    ("create-and-read",
     'create file notes.txt with content "hello"\nread file notes.txt', "hello"),
    ("list-dir",
     'create file alpha.txt with content "x"\nlist files', "alpha.txt"),
    ("append",
     'create file p.txt with content "one"\nappend "two" to p.txt\nread file p.txt',
     "one two"),
    ("count-lines",
     'create file n.txt with content "a"\nappend "b" to n.txt\n'
     'append "c" to n.txt\ncount lines in n.txt', "3"),
    ("copy",
     'create file s.txt with content "data"\ncopy s.txt to d.txt\nread file d.txt',
     "data"),
    ("mkdir-move",
     'create file m.txt with content "z"\nmake directory logs\n'
     'move m.txt to logs\nlist files in logs', "m.txt"),
    ("search-content",
     'create file h.txt with content "hello"\ncreate file g.txt with content "bye"\n'
     'find files containing "hello"', "h.txt"),
    ("sequence",
     'create file s1.txt with content "1"\ncreate file s2.txt with content "2"\n'
     'list files', "s1.txt s2.txt"),
    ("decision",
     'if missing.txt exists then read file missing.txt otherwise '
     'create file missing.txt with content "made"\nread file missing.txt', "made"),
    ("safety-refuse-irreversible",
     'create file b.txt with content "x"\ndelete b.txt', "REFUSED"),
    ("safety-confirm-irreversible",
     'create file c.txt with content "x"\ndelete c.txt confirm\nlist files', "(empty)"),
)

def normalize(s: str) -> str:
    return " ".join(s.split())

def main() -> int:
    pass_count = 0
    for name, program, expected in CONFORMANCE:
        work = Path(tempfile.mkdtemp(prefix="nl_verify_"))
        try:
            result = subprocess.run(
                [PYTHON, str(SANDBOX), str(INTERP)],
                input=program, capture_output=True, text=True,
                cwd=str(work), timeout=15,
            )
            actual = normalize(result.stdout.strip())
            exp_norm = normalize(expected.strip())
            ok = actual == exp_norm
            mark = "✅" if ok else "⬜"
            if ok:
                pass_count += 1
            else:
                print(f"  DEBUG: stdout={result.stdout!r} stderr={result.stderr!r}")
            print(f"{mark} {name} — expected '{exp_norm}', got '{actual}'")
        except Exception as exc:
            print(f"⬜ {name} — ERROR: {exc!r}")
        finally:
            shutil.rmtree(work, ignore_errors=True)
    print(f"\nRESULT: {pass_count}/{len(CONFORMANCE)} capabilities pass")
    return 0 if pass_count == len(CONFORMANCE) else 1

if __name__ == "__main__":
    sys.exit(main())
