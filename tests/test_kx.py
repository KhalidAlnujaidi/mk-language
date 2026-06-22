"""Tests for the kx CLI entrypoint — doctor and new subcommands.

TDD Step 1: write these tests first; they must be RED before implementation.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent


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


def test_kx_new_scaffolds_next_md(tmp_path: Path) -> None:
    name = "demoproj"
    out = subprocess.run(
        [sys.executable, str(REPO / "kx"), "new", name],
        capture_output=True,
        text=True,
        cwd=str(REPO),
    )
    assert out.returncode == 0
    p = REPO / "projects" / name / "next.md"
    assert p.exists()
    p.unlink()
    (REPO / "projects" / name).rmdir()  # clean up scaffolded fixture
