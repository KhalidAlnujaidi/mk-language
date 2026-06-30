"""Stage: recent_files — temporal decay file weighting (anti-RAG hack).

Thesis #1: ground truth beats the model — pure git subprocess, no model call.
Thesis #2: fail-direction is SOFT — degrades to empty ContextResult.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from kernel.contracts import FailDirection
from products.groom.stages.context import ContextResult

FAIL_DIRECTION: FailDirection = FailDirection.SOFT

_GIT_TIMEOUT: int = 5  # seconds
_MAX_FILES: int = 10


def gather(cwd: Path) -> ContextResult:
    """Return the most recently modified files in the git repository.
    
    Extracts up to _MAX_FILES unique files.
    Returns ``ContextResult(())`` if cwd is not a git repo, git is missing,
    or any error occurs — never raises (SOFT).
    """
    try:
        result = subprocess.run(
            ["git", "-C", str(cwd), "log", "-n", "50", "--name-only", "--pretty=format:"],
            capture_output=True,
            text=True,
            timeout=_GIT_TIMEOUT,
        )
        if result.returncode != 0:
            return ContextResult(())
            
        seen: set[str] = set()
        recent_files: list[str] = []
        
        for line in result.stdout.splitlines():
            file_path = line.strip()
            if file_path and file_path not in seen:
                # Only include if file actually exists in the working directory
                # (to exclude deleted files from the recent log)
                if (cwd / file_path).exists():
                    seen.add(file_path)
                    recent_files.append(file_path)
            
            if len(recent_files) >= _MAX_FILES:
                break

        if not recent_files:
            return ContextResult(())

        files_str = ", ".join(recent_files)
        return ContextResult(lines=(f"git.recent_files=[{files_str}]",))
    except Exception:
        return ContextResult(())
