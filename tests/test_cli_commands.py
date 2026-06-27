"""kx CLI command logic (vision §5.2 Layer 0/2, §8.2).

The bare `kx` menu stays stdlib for cold-start; these are the testable cores
behind the subcommands. (Chose the existing stdlib dispatcher over Typer to
honor the kx cold-start discipline — Rule Zero: reuse what's there.)
"""

from __future__ import annotations

from pathlib import Path

import pytest
from daemon.doctor import Finding
from products.cli.commands import (
    format_doctor_findings,
    init_project_repo,
    scaffold_project,
)


def _git_available() -> bool:
    import shutil

    return shutil.which("git") is not None


def test_scaffold_creates_project_with_capped_next_md(tmp_path: Path):
    path = scaffold_project(tmp_path, "demo")
    assert path == tmp_path / "demo"
    assert (path / "next.md").exists()
    assert (path / "next.md").read_text().strip() != ""


def test_scaffold_rejects_reserved_name(tmp_path: Path):
    with pytest.raises(ValueError):
        scaffold_project(tmp_path, "kin")


def test_scaffold_is_idempotent_safe(tmp_path: Path):
    scaffold_project(tmp_path, "demo")
    # re-scaffolding an existing project must not raise or clobber next.md
    (tmp_path / "demo" / "next.md").write_text("user edits")
    scaffold_project(tmp_path, "demo")
    assert (tmp_path / "demo" / "next.md").read_text() == "user edits"


def test_scaffold_makes_project_its_own_repo(tmp_path: Path):
    """Every project is its own isolated git repo with a baseline commit."""
    if not _git_available():
        pytest.skip("git not available")
    path = scaffold_project(tmp_path, "demo")
    assert (path / ".git").is_dir()  # isolated repo, not the framework's
    assert (path / ".gitignore").exists()
    import subprocess

    log = subprocess.run(
        ["git", "log", "--oneline"], cwd=path, capture_output=True, text=True
    )
    assert log.returncode == 0 and log.stdout.strip()  # has the baseline commit
    branch = subprocess.run(
        ["git", "branch", "--show-current"], cwd=path, capture_output=True, text=True
    )
    assert branch.stdout.strip() == "main"  # standardized default branch


def test_init_project_repo_excludes_scratch(tmp_path: Path):
    """Agent scratch (.remember/.deepseek/logs) is gitignored, not committed."""
    if not _git_available():
        pytest.skip("git not available")
    proj = tmp_path / "p"
    proj.mkdir()
    (proj / "work.md").write_text("real work")
    (proj / ".remember").mkdir()
    (proj / ".remember" / "session.log").write_text("scratch")
    assert init_project_repo(proj) is True
    import subprocess

    tracked = subprocess.run(
        ["git", "ls-files"], cwd=proj, capture_output=True, text=True
    ).stdout
    assert "work.md" in tracked
    assert ".remember" not in tracked  # scratch excluded


def test_init_project_repo_idempotent(tmp_path: Path):
    if not _git_available():
        pytest.skip("git not available")
    proj = tmp_path / "p"
    proj.mkdir()
    assert init_project_repo(proj) is True
    assert init_project_repo(proj) is True  # second call is a no-op, still True


def test_format_doctor_findings_clean_and_with_findings():
    assert "healthy" in format_doctor_findings([]).lower()
    out = format_doctor_findings(
        [
            Finding("missing_model", "qwen", fixable=True),
            Finding("checksum_drift", "alignment/CONSTITUTION.md", fixable=False),
        ]
    )
    assert "missing_model" in out
    assert "qwen" in out
    assert "checksum_drift" in out
