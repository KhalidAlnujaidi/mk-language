"""Stage: context — deterministic git/fs workspace context.

Thesis #1: ground truth beats the model — pure git subprocess, no model call.
Thesis #2: fail-direction is SOFT (optimizer); degrades to empty ContextResult.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path

from kernel.contracts import FailDirection

FAIL_DIRECTION: FailDirection = FailDirection.SOFT

_GIT_TIMEOUT: int = 5  # seconds; caps the subprocess


@dataclass(frozen=True)
class ContextResult:
    """Git/fs context lines, each formatted as ``key=value``."""

    lines: tuple[str, ...]


def gather(cwd: Path) -> ContextResult:
    """Return git branch and changed-file count as context lines.

    Returns ``ContextResult(())`` if cwd is not a git repo, git is missing,
    or any error occurs — never raises (SOFT).
    """
    try:
        branch_result = subprocess.run(
            ["git", "-C", str(cwd), "rev-parse", "--abbrev-ref", "HEAD"],
            capture_output=True,
            text=True,
            timeout=_GIT_TIMEOUT,
        )
        if branch_result.returncode != 0:
            return ContextResult(())
        branch = branch_result.stdout.strip()

        status_result = subprocess.run(
            ["git", "-C", str(cwd), "status", "--porcelain"],
            capture_output=True,
            text=True,
            timeout=_GIT_TIMEOUT,
        )
        if status_result.returncode != 0:
            return ContextResult(())
        changed = len([ln for ln in status_result.stdout.splitlines() if ln.strip()])

        return ContextResult(
            lines=(
                f"git.branch={branch}",
                f"git.changed_files={changed}",
            )
        )
    except Exception:
        return ContextResult(())
