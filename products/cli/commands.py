"""Testable cores behind the kx subcommands (vision §5.2, §8.2).

The bare ``kx`` menu stays stdlib for a fast cold start; the actual command
logic lives here as pure-ish functions the dispatcher calls (and tests drive
directly). I/O is confined to the filesystem; no heavy imports at module load.
"""

from __future__ import annotations

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
