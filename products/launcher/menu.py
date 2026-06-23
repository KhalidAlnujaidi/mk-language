"""The pure menu model behind the launcher hub (design §"Architecture").

Data only: ``build_menu`` turns the ``projects/`` directory into the rows the hub
shows — admin scope first, one row per project, then the action rows. No
selection, no rendering, no subprocesses; those live in ``app.py``. Keeping this
pure makes the whole menu trivially unit-testable without a terminal.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

#: The kinds of row the hub can show. ``admin``/``project`` carry a ``scope_dir``
#: to launch claude in; the rest are actions handled by the loop itself.
MenuKind = Literal["admin", "project", "new", "dashboard", "doctor", "quit"]


@dataclass(frozen=True)
class MenuItem:
    """One row in the hub. ``scope_dir`` is set only for launchable scopes."""

    key: str
    label: str
    kind: MenuKind
    scope_dir: Path | None = None


def _project_dirs(projects_dir: Path) -> list[Path]:
    """Sorted project subdirs, ignoring dotfiles / ``.gitkeep`` / stray files.

    A fresh checkout may not have ``projects/`` yet — treat that as no projects
    rather than raising.
    """
    if not projects_dir.is_dir():
        return []
    dirs = [
        p
        for p in projects_dir.iterdir()
        if p.is_dir() and not p.name.startswith(".")
    ]
    return sorted(dirs, key=lambda p: p.name)


def build_menu(
    projects_dir: Path, *, role: str = "admin", manifest: object | None = None
) -> list[MenuItem]:
    """Build the hub rows for the given ``projects/`` dir, filtered by ``role``.

    The repo root is the parent of ``projects_dir`` (the admin scope). The
    ``developer`` role omits the admin scope row — developers work inside
    ``projects/`` only (enforced separately by the dev-guard hook). ``manifest``
    is accepted for future label enrichment and is not used yet.
    """
    repo_root = projects_dir.parent
    items: list[MenuItem] = []
    if role != "developer":
        items.append(
            MenuItem("kin", "kin — admin scope (repo root)", "admin", repo_root)
        )
    for project in _project_dirs(projects_dir):
        items.append(
            MenuItem(project.name, f"{project.name} — project", "project", project)
        )
    items.extend(
        [
            MenuItem("new", "+ new project…", "new"),
            MenuItem("dashboard", "dashboard — observability", "dashboard"),
            MenuItem("doctor", "doctor — health check", "doctor"),
            MenuItem("quit", "quit", "quit"),
        ]
    )
    return items
