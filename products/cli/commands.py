"""Testable cores behind the kx subcommands (vision §5.2, §8.2).

The bare ``kx`` menu stays stdlib for a fast cold start; the actual command
logic lives here as pure-ish functions the dispatcher calls (and tests drive
directly). I/O is confined to the filesystem; no heavy imports at module load.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from daemon.doctor import Finding

#: Reserved admin/core scope — never a project name (the "keyword jail").
RESERVED = frozenset({"kin"})

_NEXT_MD_TEMPLATE = """\
# {name} — next.md

> Working memory for this project. Keep it short; it is injected into context.

## Now
- (what you're doing)

## Boundaries
- (protected files / what not to touch)
"""

#: Per-project ignore list — agent scratch and runtime, never the work itself.
#: A project is its own isolated repo, unaware of the framework that runs it.
_PROJECT_GITIGNORE = """\
# Agent session scratch / memory (not project artifacts)
.remember/
.deepseek/

# Runtime / logs
*.log
*.pid

# Regenerable caches (embeddings, etc.) — not source artifacts
.cache/
*.cache
.emb_cache*

# Timestamped session / prompt captures (scratch)
20[0-9][0-9]-[0-9][0-9]-[0-9][0-9]-*.txt

# Python
__pycache__/
*.py[cod]
.venv/
.pytest_cache/
.ruff_cache/

# OS / editor junk
.DS_Store
._*
*.swp
*.bak
"""


def init_project_repo(project: Path) -> bool:
    """Make *project* its own isolated git repo with a baseline commit.

    Idempotent (an existing ``.git`` is left untouched) and **fail-soft**: if git
    is unavailable or a step fails, returns ``False`` without raising — a project
    that can't be versioned is still a usable project. Writes a project-scoped
    ``.gitignore`` (agent scratch excluded) and commits the current contents so
    the project starts from a recoverable baseline, separate from the framework.
    """
    if (project / ".git").exists():
        return True
    gitignore = project / ".gitignore"
    if not gitignore.exists():
        gitignore.write_text(_PROJECT_GITIGNORE, encoding="utf-8")

    def _git(*args: str) -> bool:
        try:
            r = subprocess.run(  # noqa: S603 — fixed git args, project-local
                ["git", *args],
                cwd=str(project),
                capture_output=True,
                text=True,
                timeout=30,
            )
        except (OSError, subprocess.SubprocessError):
            return False
        return r.returncode == 0

    if not _git("init", "-q"):
        return False
    # Best-effort identity so the baseline commit never fails on a fresh machine.
    _git("config", "user.name", "kinox")
    _git("config", "user.email", "kinox@localhost")
    if not _git("add", "-A"):
        return False
    return _git("commit", "-q", "-m", "chore: initialize project baseline")


def scaffold_project(projects_root: Path, name: str) -> Path:
    """Create ``projects_root/<name>/`` with a starter ``next.md``.

    Idempotent: an existing project is left untouched (never clobber next.md).
    Rejects the reserved ``kin`` scope.
    """
    if name in RESERVED:
        raise ValueError(
            f"'{name}' is the reserved admin/core scope, not a project name"
        )
    project = projects_root / name
    project.mkdir(parents=True, exist_ok=True)
    next_md = project / "next.md"
    if not next_md.exists():
        next_md.write_text(_NEXT_MD_TEMPLATE.format(name=name), encoding="utf-8")
    # Every project is its own isolated repo (own baseline, unaware of the
    # framework). Fail-soft: a project without git still works.
    init_project_repo(project)
    return project


def format_doctor_findings(findings: list[Finding]) -> str:
    """Render doctor findings as text; a clean system reports healthy."""
    if not findings:
        return "kx doctor: healthy — no drift detected."
    lines = ["kx doctor: findings"]
    for f in findings:
        tag = "auto-fixable" if f.fixable else "needs human"
        lines.append(f"  - [{f.kind}] {f.detail} ({tag})")
    return "\n".join(lines)
