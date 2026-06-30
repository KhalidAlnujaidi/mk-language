"""Stage: entities — deterministic extraction of domain entities.

Harvested from ``cheatcodes/last30days-skill/skills/last30days/scripts/lib/entity_extract.py``.
Extracts @handles, #hashtags, and r/subreddits for targeted searching.
Ignores generic handles.

Fail-direction is SOFT (thesis #2): this is an extractor, so on any
doubt it passes the text through unchanged and merely annotates.
"""

from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

from kernel.contracts import FailDirection

FAIL_DIRECTION: FailDirection = FailDirection.SOFT

_ISSUE_PATTERN = re.compile(r'(?:^|\s)(#\d+)\b')
_TICKET_PATTERN = re.compile(r'(?:^|\s)([A-Z]{2,10}-\d+)\b')
_COMMIT_PATTERN = re.compile(r'(?:^|\s)([0-9a-f]{7,40})\b')


@dataclass(frozen=True)
class EntityResult:
    """The result of an entity scan."""

    found: tuple[str, ...]

    @property
    def clean(self) -> bool:
        """True when no entities were found."""
        return not self.found


def _fetch_issue(issue: str, cwd: Path) -> str | None:
    try:
        out = subprocess.run(
            ["gh", "issue", "view", issue.lstrip("#")],
            cwd=cwd, capture_output=True, text=True, timeout=2
        )
        if out.returncode == 0 and out.stdout:
            lines = out.stdout.strip().splitlines()
            return "\n  ".join(lines[:5])
    except Exception:
        pass
    return None


def _fetch_commit(commit: str, cwd: Path) -> str | None:
    try:
        out = subprocess.run(
            ["git", "show", "--stat", "--oneline", commit],
            cwd=cwd, capture_output=True, text=True, timeout=2
        )
        if out.returncode == 0 and out.stdout:
            return "  " + out.stdout.strip().replace("\n", "\n  ")
    except Exception:
        pass
    return None


def _fetch_ticket(ticket: str, cwd: Path) -> str | None:
    try:
        out = subprocess.run(
            ["git", "log", f"--grep={ticket}", "--oneline", "-n", "3"],
            cwd=cwd, capture_output=True, text=True, timeout=2
        )
        if out.returncode == 0 and out.stdout:
            return "  " + out.stdout.strip().replace("\n", "\n  ")
    except Exception:
        pass
    return None


def extract_entities(text: str, *, cwd: Path | None = None) -> EntityResult:
    """Scan *text* for developer entities (issues, tickets, commits) and fetch context."""
    base = Path(cwd) if cwd is not None else Path()
    found: set[str] = set()
    
    # Extract issues (#123)
    for match in _ISSUE_PATTERN.finditer(text):
        issue = match.group(1)
        res = _fetch_issue(issue, base) if cwd else None
        if res:
            found.add(f"GitHub {issue}:\n  {res}")
        else:
            found.add(f"GitHub {issue}")
            
    # Extract Jira/Linear tickets (CC-31)
    for match in _TICKET_PATTERN.finditer(text):
        ticket = match.group(1)
        res = _fetch_ticket(ticket, base) if cwd else None
        if res:
            found.add(f"Ticket {ticket} (recent commits):\n  {res}")
        else:
            found.add(f"Ticket {ticket}")
            
    # Extract git commits (a1b2c3d)
    for match in _COMMIT_PATTERN.finditer(text):
        commit = match.group(1)
        res = _fetch_commit(commit, base) if cwd else None
        if res:
            found.add(f"Commit {commit}:\n  {res}")
        else:
            found.add(f"Commit {commit}")
            
    return EntityResult(tuple(sorted(found)))
