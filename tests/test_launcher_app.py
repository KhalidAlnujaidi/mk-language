"""Tests for the launcher hub loop (G4-2).

The loop's job is dispatch: present the menu, route the choice, and return to the
menu until the user quits. All terminal interaction is injected (``select``,
``spawn``, action handlers) so the routing is testable without a real TTY or
``questionary``.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import products.launcher.app as app
import pytest
from products.launcher.app import make_kin_spawner, run
from products.launcher.menu import MenuItem


def _selector(*keys: str) -> Callable[[list[MenuItem]], MenuItem | None]:
    """A fake ``select`` that returns items by key, in order, then quits.

    Falls back to the ``quit`` row when the script is exhausted so a buggy loop
    can never hang the test.
    """
    queue = list(keys)

    def select(items: list[MenuItem]) -> MenuItem | None:
        if not queue:
            return next(i for i in items if i.kind == "quit")
        key = queue.pop(0)
        return next(i for i in items if i.key == key)

    return select


def _projects(tmp_path: Path, *names: str) -> Path:
    projects = tmp_path / "projects"
    projects.mkdir()
    for n in names:
        (projects / n).mkdir()
    return projects


def test_selecting_a_scope_spawns_then_returns_to_menu(tmp_path: Path) -> None:
    projects = _projects(tmp_path, "alpha")
    spawned: list[Path] = []
    rc = run(
        projects_dir=projects,
        select=_selector("alpha", "quit"),
        spawn=lambda scope: spawned.append(scope),
    )
    assert rc == 0
    assert spawned == [projects / "alpha"]  # spawned once, then looped to quit


def test_admin_scope_spawns_repo_root(tmp_path: Path) -> None:
    projects = _projects(tmp_path)
    spawned: list[Path] = []
    run(
        projects_dir=projects,
        select=_selector("kin", "quit"),
        spawn=lambda scope: spawned.append(scope),
    )
    assert spawned == [tmp_path]  # repo root = parent of projects/


def test_quit_exits_zero_without_spawning(tmp_path: Path) -> None:
    projects = _projects(tmp_path, "alpha")
    spawned: list[Path] = []
    rc = run(
        projects_dir=projects,
        select=_selector("quit"),
        spawn=lambda scope: spawned.append(scope),
    )
    assert rc == 0
    assert spawned == []


def test_select_none_exits_zero(tmp_path: Path) -> None:
    projects = _projects(tmp_path)
    rc = run(
        projects_dir=projects,
        select=lambda items: None,
        spawn=lambda scope: None,
    )
    assert rc == 0


def test_dashboard_and_doctor_dispatch_then_loop(tmp_path: Path) -> None:
    projects = _projects(tmp_path)
    calls: list[str] = []
    rc = run(
        projects_dir=projects,
        select=_selector("dashboard", "doctor", "quit"),
        spawn=lambda scope: calls.append("spawn"),
        dashboard=lambda: calls.append("dashboard"),
        doctor=lambda: calls.append("doctor"),
    )
    assert rc == 0
    assert calls == ["dashboard", "doctor"]  # both ran, no spawn, ended at quit


def test_new_project_scaffolds_and_enters(tmp_path: Path) -> None:
    projects = _projects(tmp_path)
    new_dir = projects / "fresh"
    spawned: list[Path] = []
    rc = run(
        projects_dir=projects,
        select=_selector("new", "quit"),
        spawn=lambda scope: spawned.append(scope),
        new_project=lambda: new_dir,  # returns the scope to enter
    )
    assert rc == 0
    assert spawned == [new_dir]


def test_new_project_cancelled_does_not_spawn(tmp_path: Path) -> None:
    projects = _projects(tmp_path)
    spawned: list[Path] = []
    rc = run(
        projects_dir=projects,
        select=_selector("new", "quit"),
        spawn=lambda scope: spawned.append(scope),
        new_project=lambda: None,  # cancelled
    )
    assert rc == 0
    assert spawned == []


def test_non_tty_plan_reflects_role(tmp_path: Path, capsys: object) -> None:
    projects = _projects(tmp_path, "alpha")
    run(projects_dir=projects, spawn=lambda _: None, is_tty=False, role="admin")
    admin_out = capsys.readouterr().out  # type: ignore[attr-defined]
    assert "admin scope" in admin_out

    run(projects_dir=projects, spawn=lambda _: None, is_tty=False, role="developer")
    dev_out = capsys.readouterr().out  # type: ignore[attr-defined]
    assert "admin scope" not in dev_out  # developer never sees the admin row
    assert "alpha" in dev_out


def test_make_kin_spawner_sets_role_env() -> None:
    calls: list[tuple[list[str], dict[str, str]]] = []
    spawn = make_kin_spawner(
        Path("/repo/kin"),
        role="developer",
        runner=lambda argv, env: calls.append((argv, env)),
    )
    spawn(Path("/repo/projects/alpha"))
    _, env = calls[0]
    assert env["KINOX_ROLE"] == "developer"
    assert env["KIN_SCOPE_DIR"] == "/repo/projects/alpha"


def test_text_role_select() -> None:
    assert app.text_role_select(prompt=lambda _: "1") == "admin"
    assert app.text_role_select(prompt=lambda _: "2") == "developer"
    assert app.text_role_select(prompt=lambda _: "") == "admin"  # default
    assert app.text_role_select(prompt=lambda _: "9") == "admin"  # out of range


def test_select_role_falls_back_to_text_without_questionary(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(app, "_import_questionary", lambda: None)
    assert app.select_role(prompt=lambda _: "2") == "developer"


def test_make_kin_spawner_runs_kin_claude_with_scope_env() -> None:
    # The hub launches by SPAWNING `kin claude` (subprocess, so it returns) with
    # the scope passed via KIN_SCOPE_DIR — not execve.
    calls: list[tuple[list[str], dict[str, str]]] = []
    spawn = make_kin_spawner(
        Path("/repo/kin"),
        runner=lambda argv, env: calls.append((argv, env)),
    )
    spawn(Path("/repo/projects/alpha"))
    assert len(calls) == 1
    argv, env = calls[0]
    assert argv == ["/repo/kin", "claude"]  # claude mode = direct launch, no hub
    assert env["KIN_SCOPE_DIR"] == "/repo/projects/alpha"


def test_non_tty_prints_plan_and_never_selects(
    tmp_path: Path, capsys: object
) -> None:
    projects = _projects(tmp_path, "alpha")

    def exploding_select(items: list[MenuItem]) -> MenuItem | None:
        raise AssertionError("select must not be called without a TTY")

    rc = run(
        projects_dir=projects,
        select=exploding_select,
        spawn=lambda scope: None,
        is_tty=False,
    )
    assert rc == 0
    out = capsys.readouterr().out  # type: ignore[attr-defined]
    assert "kin" in out and "alpha" in out  # the menu was printed as a plan
