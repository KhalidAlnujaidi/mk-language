"""Tests for the kx CLI entrypoint — doctor and new subcommands.

TDD Step 1: write these tests first; they must be RED before implementation.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent


def test_bare_kx_opens_the_launcher_hub_non_interactively() -> None:
    # Bare `kx` is now the default working environment (the hub). With no TTY it
    # prints the menu as a plan and exits 0 — never blocking on selection.
    out = subprocess.run(
        [sys.executable, str(REPO / "kx")],
        capture_output=True,
        text=True,
        stdin=subprocess.DEVNULL,
        timeout=30,
    )
    assert out.returncode == 0
    assert "hub" in out.stdout.lower()  # launcher hub plan, not the old static menu
    assert "kin" in out.stdout.lower()  # the admin row is listed


def test_kx_doctor_runs_and_reports() -> None:
    out = subprocess.run(
        [sys.executable, str(REPO / "kx"), "doctor"],
        capture_output=True,
        text=True,
    )
    assert out.returncode == 0
    assert "cloud:" in out.stdout.lower()


def test_kx_new_rejects_reserved_scope() -> None:
    out = subprocess.run(
        [sys.executable, str(REPO / "kx"), "new", "kin"],
        capture_output=True,
        text=True,
    )
    assert out.returncode == 2


def test_kx_kin_enters_admin_scope_not_rejected() -> None:
    # `kx kin` is no longer a rejection — it hands off to the kin admin scope.
    out = subprocess.run(
        [sys.executable, str(REPO / "kx"), "kin"],
        capture_output=True,
        text=True,
        stdin=subprocess.DEVNULL,
        timeout=30,
    )
    assert out.returncode == 0
    assert "admin" in out.stdout.lower()


def test_kx_new_scaffolds_next_md(tmp_path: Path) -> None:
    name = "demoproj"
    out = subprocess.run(
        [sys.executable, str(REPO / "kx"), "new", name],
        capture_output=True,
        text=True,
        stdin=subprocess.DEVNULL,  # no TTY → scaffolds, prints plan, does not launch
        cwd=str(REPO),
        timeout=30,
    )
    assert out.returncode == 0
    p = REPO / "projects" / name / "next.md"
    assert p.exists()
    p.unlink()
    (REPO / "projects" / name).rmdir()  # clean up scaffolded fixture


def test_kx_new_then_launches_claude_in_the_project() -> None:
    # `kx new` scaffolds AND enters a governed Claude Code session in the project
    # dir (non-TTY here, so we see the launch PLAN rather than a real launch).
    name = "demolaunch"
    project = REPO / "projects" / name
    out = subprocess.run(
        [sys.executable, str(REPO / "kx"), "new", name],
        capture_output=True,
        text=True,
        stdin=subprocess.DEVNULL,
        cwd=str(REPO),
        timeout=30,
    )
    try:
        assert out.returncode == 0
        assert "claude --dangerously-skip-permissions" in out.stdout
        assert str(project) in out.stdout  # scope is the new project's dir
    finally:
        (project / "next.md").unlink(missing_ok=True)
        if project.exists():
            project.rmdir()


def test_kx_activate_existing_project_launches_claude() -> None:
    name = "demoactivate"
    project = REPO / "projects" / name
    subprocess.run(
        [sys.executable, str(REPO / "kx"), "new", name],
        capture_output=True,
        text=True,
        stdin=subprocess.DEVNULL,
        cwd=str(REPO),
        timeout=30,
    )
    try:
        out = subprocess.run(
            [sys.executable, str(REPO / "kx"), name],
            capture_output=True,
            text=True,
            stdin=subprocess.DEVNULL,
            timeout=30,
        )
        assert out.returncode == 0
        assert "claude --dangerously-skip-permissions" in out.stdout
        assert str(project) in out.stdout
    finally:
        (project / "next.md").unlink(missing_ok=True)
        if project.exists():
            project.rmdir()


def test_kx_activate_missing_project_hints_new() -> None:
    out = subprocess.run(
        [sys.executable, str(REPO / "kx"), "no_such_project_xyz"],
        capture_output=True,
        text=True,
        stdin=subprocess.DEVNULL,
        timeout=30,
    )
    assert out.returncode == 2
    assert "kx new" in out.stdout
