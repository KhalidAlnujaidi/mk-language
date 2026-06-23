"""Tests for the `kin` admin entrypoint.

`kin` is the reserved admin/core scope: from anywhere it drops you into an
interactive admin subshell rooted at the kinox repo. The interactive subshell
can't be unit-tested, but the load-bearing behaviour can: it must resolve the
repo root even when invoked through a PATH symlink, and it must NOT hang when
stdin is not a TTY (CI / pipes) — it reports and exits instead.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
KIN = REPO / "kin"


def test_kin_script_exists_and_is_executable() -> None:
    assert KIN.exists()
    assert os.access(KIN, os.X_OK)


def test_kin_reports_repo_root_non_interactively() -> None:
    # No TTY on stdin → must report where it would drop you and exit 0, not hang.
    out = subprocess.run(
        [str(KIN)],
        capture_output=True,
        text=True,
        stdin=subprocess.DEVNULL,
        cwd="/tmp",
        timeout=30,
    )
    assert out.returncode == 0
    assert str(REPO) in out.stdout
    assert "admin" in out.stdout.lower()


def test_kin_resolves_repo_root_through_a_symlink(tmp_path: Path) -> None:
    # Invoked via a symlink from an unrelated dir, it must still resolve to the
    # real repo root (the whole point of "run it from anywhere").
    link = tmp_path / "kin"
    link.symlink_to(KIN)
    out = subprocess.run(
        [str(link)],
        capture_output=True,
        text=True,
        stdin=subprocess.DEVNULL,
        cwd=str(tmp_path),
        timeout=30,
    )
    assert out.returncode == 0
    assert str(REPO) in out.stdout  # resolved through the symlink, not tmp_path


def _run_kin(
    *args: str, env: dict[str, str] | None = None
) -> subprocess.CompletedProcess[str]:
    full_env = {**os.environ, **(env or {})}
    return subprocess.run(
        [str(KIN), *args],
        capture_output=True,
        text=True,
        stdin=subprocess.DEVNULL,  # no TTY → prints the plan and exits, never launches
        cwd="/tmp",
        timeout=30,
        env=full_env,
    )


def test_kin_default_plan_launches_claude_with_skip_permissions() -> None:
    out = _run_kin()
    assert out.returncode == 0
    assert "claude --dangerously-skip-permissions" in out.stdout


def test_kin_shell_mode_plans_an_admin_shell() -> None:
    out = _run_kin("shell")
    assert out.returncode == 0
    assert "admin shell" in out.stdout.lower()
    assert "claude" not in out.stdout.lower()  # shell mode does not launch claude


def test_kin_claude_args_are_overridable() -> None:
    out = _run_kin(env={"KIN_CLAUDE_ARGS": "--model opus --foo"})
    assert out.returncode == 0
    assert "claude --model opus --foo" in out.stdout
    assert "dangerously" not in out.stdout  # the override replaces the default flag
