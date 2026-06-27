"""Isolated runner for the v03 TERMINAL backend.

Invoked as a subprocess by council.score_interpreter(mode='shell') — never imported.
Reads the intent program from stdin, exec's the council-generated TRANSLATOR file given
as argv[1], calls its `translate(source)` entry to get a POSIX shell script, then RUNS
that script with /bin/sh in the current working dir (the parent's fresh sandbox) and
writes its stdout. So the verified artifact is the emitted terminal command itself.

Containment (model-written shell is riskier than model-written Python):
  - runs in the parent-chosen temp sandbox cwd, with a minimal env (PATH=/usr/bin:/bin,
    HOME=cwd) so `~`/$HOME can't escape;
  - inherits the parent's CPU/AS/FSIZE rlimits;
  - a denylist hard-REFUSES obviously dangerous scripts (rm -rf /, sudo, mkfs, fork
    bombs, absolute system paths, network tools) before anything runs — fail-CLOSED.
"""

from __future__ import annotations

import inspect
import os
import re
import subprocess
import sys

_ENTRY = ("translate", "compile", "emit", "to_shell", "run", "main")

# Fail-CLOSED denylist: refuse to run a script matching a genuinely catastrophic
# pattern. Tuned to block escapes/destruction WITHOUT tripping on safe idioms like
# `2>/dev/null` or a relative `rm file` (the sandbox cwd + rlimits + the relative-path
# contract are the primary containment; this is the catastrophe backstop).
_DENY = re.compile(
    r"(\brm\s+-rf?\s+(/|~|\$)"                       # rm -rf on /, ~, or a var
    r"|\bsudo\b|\bmkfs|\bdd\s+if="                   # privilege / raw disk
    r"|:\s*\(\)\s*\{[^}]*\}\s*;\s*:"                 # classic fork bomb
    r"|\b(curl|wget|nc|ncat|ssh|scp|telnet|ftp)\b"  # network egress
    r"|>\s*/(etc|sys|proc|boot|usr|bin|lib|root|var)\b"  # write into system trees
    r"|\b(chmod|chown)\b[^\n]*\s/(etc|usr|bin|root)\b"   # perms on system trees
    r"|/(etc|root)/(passwd|shadow|sudoers))",
    re.IGNORECASE,
)


def _find(g: dict[str, object]):
    for n in _ENTRY:
        fn = g.get(n)
        if callable(fn):
            return fn
    for v in g.values():
        if callable(v) and not isinstance(v, type):
            try:
                ps = [p for p in inspect.signature(v).parameters.values()
                      if p.kind in (p.POSITIONAL_ONLY, p.POSITIONAL_OR_KEYWORD)
                      and p.default is p.empty]
            except (ValueError, TypeError):
                continue
            if len(ps) == 1:
                return v
    return None


try:  # inherit the same caps the Python runner uses
    import resource

    resource.setrlimit(resource.RLIMIT_CPU, (10, 12))
    resource.setrlimit(resource.RLIMIT_AS, (1 << 30, 1 << 30))
    resource.setrlimit(resource.RLIMIT_FSIZE, (1 << 24, 1 << 24))
except Exception:  # pragma: no cover - non-POSIX
    pass


def main() -> int:
    interp_path = sys.argv[1]
    program = sys.stdin.read()
    with open(interp_path, encoding="utf-8") as fh:
        code = fh.read()
    g: dict[str, object] = {"__name__": "_interp"}
    exec(compile(code, interp_path, "exec"), g)  # noqa: S102 - sandboxed by subprocess+rlimits
    fn = _find(g)
    if fn is None:
        sys.stderr.write("NO_TRANSLATE_FUNCTION")
        return 2
    try:
        script = fn(program)
    except TypeError:
        script = fn()
    script = "" if script is None else str(script)
    if not script.strip():
        sys.stderr.write("EMPTY_SCRIPT")
        return 0
    if _DENY.search(script):
        sys.stderr.write("REFUSED_DANGEROUS_SHELL")
        return 3
    env = {"PATH": "/usr/bin:/bin", "HOME": os.getcwd(), "LC_ALL": "C"}
    try:
        proc = subprocess.run(
            ["/bin/sh", "-c", script],
            capture_output=True, text=True, timeout=15, env=env,
        )
    except subprocess.TimeoutExpired:
        sys.stderr.write("SHELL_TIMEOUT")
        return 4
    sys.stdout.write(proc.stdout)
    if proc.returncode != 0 and not proc.stdout:
        sys.stderr.write((proc.stderr or "")[:200])
    return 0


if __name__ == "__main__":
    sys.exit(main())
