"""OS-enforced filesystem confinement for shell subprocesses (Landlock).

The lexical bash guard (`tools._bash_escape_reason`) is a speed bump, not a wall:
``$(...)`` command substitution, ``$VAR`` indirection, and here-docs can slip a
write past it (the constitution's hard truth #1 — real protection needs OS-level
enforcement). Landlock — a Linux LSM, unprivileged and **not** dependent on user
namespaces (so the AppArmor userns block does not defeat it) — closes that gap: a
``run_bash`` child may read and execute system paths (so the shell still works)
but can only **write** beneath its scope root. A bypass that fools the lexical
check is still physically denied by the kernel.

Fail direction (thesis #2): the *availability* check fails **soft** — where
Landlock is absent the lexical guard remains the jail — but where Landlock is
present a child that cannot install the ruleset fails **closed** (the command
errors rather than running unconfined).
"""

from __future__ import annotations

import contextlib
from collections.abc import Callable
from pathlib import Path


def landlock_available() -> bool:
    """True if the kernel exposes a usable Landlock ABI (v1+)."""
    try:
        from landlock import landlock_abi_version

        return landlock_abi_version() >= 1
    except Exception:
        return False


def _write_accesses() -> object:
    """The Landlock FS access bits that constitute a *write* (everything that
    mutates the filesystem). Read/execute/ioctl are deliberately excluded so the
    confined shell can still read libraries and run programs anywhere — only
    mutation is jailed."""
    from landlock import FSAccess

    acc = (
        FSAccess.WRITE_FILE
        | FSAccess.MAKE_REG
        | FSAccess.MAKE_DIR
        | FSAccess.MAKE_SYM
        | FSAccess.MAKE_SOCK
        | FSAccess.MAKE_FIFO
        | FSAccess.MAKE_CHAR
        | FSAccess.MAKE_BLOCK
        | FSAccess.REMOVE_DIR
        | FSAccess.REMOVE_FILE
        | FSAccess.TRUNCATE
        | FSAccess.REFER
    )
    return acc


def _scratch_dirs() -> list[str]:
    """Non-scope scratch areas a confined shell must still write to keep tools
    working: shared temp and the user cache. These are not any scope's files, so
    allowing them does not enable cross-scope overlap (the guarantee is "no writes
    into another *scope*" — another project's dir or the framework source)."""
    import os

    home = os.environ.get("HOME", "")
    cands = ["/tmp", "/var/tmp"]
    if home:
        cands += [f"{home}/.cache"]
    return cands


def write_jail_preexec(root: Path) -> Callable[[], None] | None:
    """A ``subprocess`` ``preexec_fn`` that confines the child's WRITES to *root*
    (plus shared scratch), enforced by the kernel.

    Returns ``None`` when Landlock is unavailable, so the caller transparently
    falls back to the lexical guard (fail-soft at setup). When available, the
    returned hook runs in the child after fork / before exec: it builds a ruleset
    handling only write accesses, allows them beneath *root*, the device dir (so
    ``>/dev/null`` and friends work), and shared scratch (``/tmp``, the user
    cache — not any scope's files), then restricts the child. If the install
    fails, the exception propagates and the child never execs (fail-CLOSED) — a
    command that cannot be sandboxed does not run unconfined.

    Only writes are jailed: the child keeps read/execute everywhere, so the shell
    and the tools it spawns run normally — they simply cannot create, modify, or
    delete anything outside the scope root and the shared scratch areas. A write
    that fools the lexical guard (``$VAR``/``$(...)`` indirection into another
    scope) is still denied by the kernel.
    """
    if not landlock_available():
        return None
    root_s = str(Path(root).resolve())
    scratch = _scratch_dirs()

    def _apply() -> None:  # runs in the child (post-fork, pre-exec)
        from landlock import FSAccess, Ruleset

        write = _write_accesses()
        ruleset = Ruleset(write)  # type: ignore[arg-type]
        ruleset.allow(root_s, rules=write)  # type: ignore[arg-type]
        # Device writes (redirects) — files only, no node creation under /dev.
        dev = FSAccess.WRITE_FILE | FSAccess.TRUNCATE
        with contextlib.suppress(Exception):
            ruleset.allow("/dev", rules=dev)  # type: ignore[arg-type]
        for d in scratch:
            # A missing scratch dir is simply not allowed (fail-soft).
            with contextlib.suppress(Exception):
                ruleset.allow(d, rules=write)  # type: ignore[arg-type]
        ruleset.apply()

    return _apply
