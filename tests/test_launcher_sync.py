"""Tests for the startup git-sync helper (fetch + notify, safe `kx update`).

All git calls go through an injected runner returning ``(exit_code, stdout)``,
so the decision logic is tested with no network and no real repo.
"""

from __future__ import annotations

from collections.abc import Callable

from products.launcher import sync


def _runner(
    table: dict[str, tuple[int, str]],
) -> Callable[[list[str]], tuple[int, str]]:
    """Fake git runner: dispatch on the first arg (the git subcommand)."""
    calls: list[list[str]] = []

    def run(args: list[str]) -> tuple[int, str]:
        calls.append(args)
        return table.get(args[0], (0, ""))

    run.calls = calls  # type: ignore[attr-defined]
    return run


def test_ahead_behind_parses_rev_list() -> None:
    # `git rev-list --left-right --count origin/main...main` → "<behind>\t<ahead>"
    r = _runner({"rev-list": (0, "0\t30\n")})
    assert sync.ahead_behind(runner=r) == (30, 0)  # (ahead, behind)


def test_ahead_behind_none_on_error() -> None:
    r = _runner({"rev-list": (128, "fatal: bad revision")})
    assert sync.ahead_behind(runner=r) is None


def test_status_line_messages() -> None:
    assert "up to date" in sync.status_line((0, 0))
    behind_msg = sync.status_line((0, 5))
    assert "behind" in behind_msg and "kx update" in behind_msg
    assert "ahead" in sync.status_line((3, 0))
    assert "couldn't" in sync.status_line(None)


def test_update_already_up_to_date() -> None:
    r = _runner({"rev-list": (0, "0\t0\n")})
    msg = sync.update(runner=r)
    assert "up to date" in msg
    assert ["pull", "--ff-only", "origin", "main"] not in r.calls  # type: ignore[attr-defined]


def test_update_refuses_when_dirty() -> None:
    r = _runner({"rev-list": (0, "4\t0\n"), "status": (0, " M kernel/x.py\n")})
    msg = sync.update(runner=r)
    assert "dirty" in msg
    assert ["pull", "--ff-only", "origin", "main"] not in r.calls  # type: ignore[attr-defined]


def test_update_fast_forwards_when_behind_and_clean() -> None:
    r = _runner(
        {
            "rev-list": (0, "4\t0\n"),
            "status": (0, ""),  # clean
            "pull": (0, "Updating ...\nFast-forward\n"),
        }
    )
    msg = sync.update(runner=r)
    assert "pulled 4" in msg
    assert ["pull", "--ff-only", "origin", "main"] in r.calls  # type: ignore[attr-defined]


def test_startup_status_fetches_then_reports() -> None:
    r = _runner({"rev-list": (0, "0\t2\n")})
    line = sync.startup_status(runner=r)
    assert ["fetch", "origin", "main"] in r.calls  # type: ignore[attr-defined]
    assert "ahead" in line
