"""Isolated runner: exec a council-generated interpreter and feed it one program.

Invoked as a subprocess by council.score_interpreter — never imported into the run.
Reads the program from stdin, exec's the interpreter file given as argv[1], calls its
`run(source)` entry point, and writes whatever the program produced to stdout. Both
contracts are accepted: an interpreter that PRINTS via (display ...) to stdout, and one
whose run() RETURNS the output string. Hard CPU/memory caps + the parent's wall-clock
timeout contain a runaway or pathological interpreter during the unattended overnight run.
"""

from __future__ import annotations

import contextlib
import inspect
import io
import sys

# Entry points small models reach for, in priority order. We prefer `run` (the
# contract), but accept common synonyms so a usable interpreter isn't thrown away
# over a naming quibble. Correctness is still decided by the executed output.
_ENTRY_NAMES = (
    "run", "main", "interpret", "interpreter", "evaluate",
    "execute", "repl", "run_interpreter", "run_program", "interpret_program",
)


def _find_entry(g: dict[str, object]):
    for name in _ENTRY_NAMES:
        fn = g.get(name)
        if callable(fn):
            return fn
    # Fallback: any top-level function accepting exactly one positional argument.
    for val in g.values():
        if callable(val) and not isinstance(val, type):
            try:
                params = [
                    p for p in inspect.signature(val).parameters.values()
                    if p.kind in (p.POSITIONAL_ONLY, p.POSITIONAL_OR_KEYWORD)
                    and p.default is p.empty
                ]
            except (ValueError, TypeError):
                continue
            if len(params) == 1:
                return val
    return None

try:  # POSIX resource caps — defence for an unattended loop running model-written code.
    import resource

    resource.setrlimit(resource.RLIMIT_CPU, (10, 12))
    resource.setrlimit(resource.RLIMIT_AS, (1 << 30, 1 << 30))  # 1 GiB address space
except Exception:  # pragma: no cover - non-POSIX or unavailable
    pass


def main() -> int:
    interp_path = sys.argv[1]
    program = sys.stdin.read()
    with open(interp_path, encoding="utf-8") as fh:
        code = fh.read()
    g: dict[str, object] = {"__name__": "_interp"}
    exec(compile(code, interp_path, "exec"), g)  # noqa: S102 - sandboxed by subprocess+rlimits
    entry = _find_entry(g)
    if entry is None:
        sys.stderr.write("NO_RUN_FUNCTION")
        return 2
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        try:
            result = entry(program)
        except TypeError:  # an entry that takes no argument (reads a global, etc.)
            result = entry()
    printed = buf.getvalue()
    out = printed if printed.strip() else ("" if result is None else str(result))
    sys.stdout.write(out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
