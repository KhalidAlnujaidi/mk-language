"""kx CLI command logic (vision §5.2 Layer 0/2, §8.2).

The bare `kx` menu stays stdlib for cold-start; these are the testable cores
behind the subcommands. (Chose the existing stdlib dispatcher over Typer to
honor the kx cold-start discipline — Rule Zero: reuse what's there.)
"""

from __future__ import annotations

from pathlib import Path

import pytest
from daemon.doctor import Finding
from products.cli.commands import format_doctor_findings, scaffold_project


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
