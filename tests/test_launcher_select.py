"""Tests for the real selection/rendering seams (G4-3).

The interactive questionary path needs a TTY, so it isn't unit-tested directly;
what IS load-bearing and testable: the SOFT fallback to a numbered text menu when
questionary is unavailable, and that the default seams are wired into ``run``.
"""

from __future__ import annotations

from pathlib import Path

import products.launcher.app as app
import pytest
from products.launcher.menu import build_menu


def test_text_select_returns_item_by_number() -> None:
    items = build_menu(Path("/tmp/does-not-matter"))
    # Pick row 1 (admin) via the numbered fallback, prompt injected.
    chosen = app.text_select(items, prompt=lambda _: "1")
    assert chosen is not None
    assert chosen.kind == "admin"


def test_text_select_blank_or_bad_input_cancels() -> None:
    items = build_menu(Path("/tmp/x"))
    assert app.text_select(items, prompt=lambda _: "") is None
    assert app.text_select(items, prompt=lambda _: "nope") is None
    assert app.text_select(items, prompt=lambda _: "999") is None


def test_default_select_falls_back_when_questionary_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    items = build_menu(Path("/tmp/x"))
    # Simulate questionary not installed → must use the text fallback.
    monkeypatch.setattr(app, "_import_questionary", lambda: None)
    chosen = app.default_select(items, prompt=lambda _: "1")
    assert chosen is not None
    assert chosen.kind == "admin"


def test_default_select_is_callable_and_wired_as_run_default() -> None:
    # default_select exists and run() uses it when select is omitted.
    assert callable(app.default_select)
    import inspect

    sig = inspect.signature(app.run)
    assert sig.parameters["select"].default is None  # None → default_select


def test_run_without_select_does_not_require_a_tty(tmp_path: Path) -> None:
    # With no select passed and no TTY, run still prints the plan and exits 0
    # (it must never reach questionary).
    projects = tmp_path / "projects"
    projects.mkdir()
    rc = app.run(projects_dir=projects, spawn=lambda _: None, is_tty=False)
    assert rc == 0
