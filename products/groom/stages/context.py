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

        lines_out = [
            f"git.branch={branch}",
            f"git.changed_files={changed}",
        ]

        if changed > 0:
            diff_result = subprocess.run(
                ["git", "-C", str(cwd), "diff", "HEAD"],
                capture_output=True,
                text=True,
                timeout=_GIT_TIMEOUT,
            )
            if diff_result.returncode == 0 and diff_result.stdout:
                diff_lines = diff_result.stdout.splitlines()
                if len(diff_lines) <= 150:
                    lines_out.append("git.diff:\n```diff\n" + "\n".join(diff_lines) + "\n```")
                else:
                    lines_out.append(f"git.diff: too large to auto-inject ({len(diff_lines)} lines)")

        return ContextResult(lines=tuple(lines_out))
    except Exception:
        return ContextResult(())
