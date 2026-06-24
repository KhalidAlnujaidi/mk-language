"""Tests for the pure launcher menu model (G4-1).

``build_menu`` is data-only: given the ``projects/`` dir it returns the rows the
hub shows — the admin scope first, one row per project, then the action rows. No
I/O beyond listing the projects dir; no selection, no rendering. Those live in
``app.py`` (G4-2+).
"""

from __future__ import annotations

from pathlib import Path

from products.launcher.menu import MenuItem, build_menu


def _kinds(items: list[MenuItem]) -> list[str]:
    return [i.kind for i in items]


def test_admin_scope_is_first_and_points_at_repo_root(tmp_path: Path) -> None:
    projects = tmp_path / "projects"
    projects.mkdir()
    items = build_menu(projects)
    assert items[0].kind == "admin"
    assert items[0].key == "kin"
    # repo root is the parent of the projects dir
    assert items[0].scope_dir == tmp_path


def test_one_project_row_per_subdir_sorted(tmp_path: Path) -> None:
    projects = tmp_path / "projects"
    projects.mkdir()
    (projects / "beta").mkdir()
    (projects / "alpha").mkdir()
    items = build_menu(projects)
    projs = [i for i in items if i.kind == "project"]
    assert [p.key for p in projs] == ["alpha", "beta"]  # sorted
    assert projs[0].scope_dir == projects / "alpha"
    assert projs[1].scope_dir == projects / "beta"


def test_dotfiles_and_gitkeep_are_ignored(tmp_path: Path) -> None:
    projects = tmp_path / "projects"
    projects.mkdir()
    (projects / ".gitkeep").touch()
    (projects / ".hidden").mkdir()
    (projects / "real").mkdir()
    projs = [i for i in build_menu(projects) if i.kind == "project"]
    assert [p.key for p in projs] == ["real"]


def test_action_rows_always_present(tmp_path: Path) -> None:
    projects = tmp_path / "projects"
    projects.mkdir()
    kinds = _kinds(build_menu(projects))
    for action in ("new", "chat", "dashboard", "doctor", "quit"):
        assert action in kinds


def test_empty_projects_dir_still_returns_admin_and_actions(tmp_path: Path) -> None:
    projects = tmp_path / "projects"
    projects.mkdir()
    kinds = _kinds(build_menu(projects))
    assert kinds == ["admin", "new", "chat", "dashboard", "doctor", "quit"]


def test_missing_projects_dir_does_not_crash(tmp_path: Path) -> None:
    # projects/ may not exist yet on a fresh checkout — treat as no projects.
    projects = tmp_path / "projects"  # not created
    kinds = _kinds(build_menu(projects))
    assert kinds == ["admin", "new", "chat", "dashboard", "doctor", "quit"]


def test_admin_role_includes_the_admin_scope(tmp_path: Path) -> None:
    projects = tmp_path / "projects"
    projects.mkdir()
    kinds = _kinds(build_menu(projects, role="admin"))
    assert "admin" in kinds


def test_developer_role_hides_the_admin_scope(tmp_path: Path) -> None:
    # A developer works in projects/ only — no repo-root/admin scope row.
    projects = tmp_path / "projects"
    projects.mkdir()
    (projects / "proj").mkdir()
    items = build_menu(projects, role="developer")
    kinds = _kinds(items)
    assert "admin" not in kinds
    assert "project" in kinds  # projects still listed
    for action in ("new", "chat", "dashboard", "doctor", "quit"):
        assert action in kinds


def test_every_item_has_a_nonempty_label(tmp_path: Path) -> None:
    projects = tmp_path / "projects"
    projects.mkdir()
    (projects / "demo").mkdir()
    for item in build_menu(projects):
        assert item.label.strip()
