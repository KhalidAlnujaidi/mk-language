"""OS-enforced shell confinement (Landlock).

Proves the kernel wall: a ``run_bash`` child may write inside its scope root and
shared scratch, but a write *outside* the scope — the kind of escape that fools
the lexical guard via ``$VAR``/``$(...)`` indirection — is physically denied.
Skipped where Landlock is unavailable (the sandbox fails soft to lexical there).
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest
from products.agent.sandbox import landlock_available, write_jail_preexec

_NEEDS_LANDLOCK = pytest.mark.skipif(
    not landlock_available(), reason="Landlock unavailable on this kernel"
)


def _run(cmd: str, root: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        cmd,
        shell=True,
        cwd=str(root),
        capture_output=True,
        text=True,
        preexec_fn=write_jail_preexec(root),
    )


@_NEEDS_LANDLOCK
def test_in_root_write_allowed(tmp_path: Path) -> None:
    p = _run("echo hi > inside.txt", tmp_path)
    assert p.returncode == 0
    assert (tmp_path / "inside.txt").read_text().strip() == "hi"


@_NEEDS_LANDLOCK
def test_device_redirect_allowed(tmp_path: Path) -> None:
    # Without /dev write, ``>/dev/null`` would fail and break ordinary commands.
    p = _run("ls / >/dev/null && echo ok", tmp_path)
    assert p.returncode == 0 and "ok" in p.stdout


@_NEEDS_LANDLOCK
def test_write_outside_scope_denied(tmp_path: Path) -> None:
    # $HOME (not its .cache) is normally writable but is NOT this scope nor shared
    # scratch — the kernel must deny it. An absolute target needs no shell
    # expansion: this isolates the Landlock layer from the lexical guard.
    home = os.environ.get("HOME")
    if not home:
        pytest.skip("no HOME")
    target = Path(home) / "kinox_landlock_escape_test_DELETEME"
    target.unlink(missing_ok=True)
    try:
        p = _run(f'echo pwned > "{target}"', tmp_path)
        assert p.returncode != 0  # permission denied
        assert not target.exists()  # the write never landed
    finally:
        target.unlink(missing_ok=True)


@_NEEDS_LANDLOCK
def test_read_and_execute_outside_root_still_work(tmp_path: Path) -> None:
    # Only writes are jailed — the shell must still read libs and run programs.
    p = _run("cat /etc/hostname >/dev/null && echo ranok", tmp_path)
    assert p.returncode == 0 and "ranok" in p.stdout


def test_preexec_is_none_without_landlock(monkeypatch: pytest.MonkeyPatch) -> None:
    # Fail-soft at setup: if Landlock is unavailable, the hook is None and the
    # caller (bash_tool) transparently falls back to the lexical guard.
    monkeypatch.setattr(
        "products.agent.sandbox.landlock_available", lambda: False
    )
    assert write_jail_preexec(Path("/tmp")) is None
