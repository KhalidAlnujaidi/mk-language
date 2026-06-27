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


# --- launch-time self-upgrade (auto_update) ---------------------------------
#
# auto_update issues several distinct git calls (two `rev-parse` variants among
# them), so the fake runner here keys on a distinctive token in the FULL arg
# list rather than just the subcommand.


def _seq_runner(
    table: dict[str, tuple[int, str]],
) -> Callable[[list[str]], tuple[int, str]]:
    """Fake git runner: first table key found in the joined args wins."""
    calls: list[list[str]] = []

    def run(args: list[str]) -> tuple[int, str]:
        calls.append(args)
        joined = " ".join(args)
        for key, result in table.items():
            if key in joined:
                return result
        return (0, "")

    run.calls = calls  # type: ignore[attr-defined]
    return run


def _on_main(extra: dict[str, tuple[int, str]]) -> dict[str, tuple[int, str]]:
    base = {
        "abbrev-ref HEAD": (0, "main\n"),
        "symbolic-full-name": (0, "origin/main\n"),
    }
    base.update(extra)
    return base


def test_current_branch_and_upstream_parse() -> None:
    r = _seq_runner(
        {"abbrev-ref HEAD": (0, "feature-x\n"), "symbolic-full-name": (0, "origin/x\n")}
    )
    assert sync.current_branch(runner=r) == "feature-x"
    assert sync.upstream(runner=r) == "origin/x"


def test_current_branch_none_when_detached() -> None:
    r = _seq_runner({"abbrev-ref HEAD": (0, "HEAD\n")})  # detached
    assert sync.current_branch(runner=r) is None


def test_upstream_none_when_unset() -> None:
    r = _seq_runner({"symbolic-full-name": (128, "fatal: no upstream configured")})
    assert sync.upstream(runner=r) is None


def test_auto_update_fast_forwards_when_behind_and_clean() -> None:
    r = _seq_runner(
        _on_main(
            {
                "rev-list": (0, "3\t0\n"),  # 3 behind, 0 ahead
                "status": (0, ""),  # clean
                "merge": (0, ""),  # ff-only succeeds
            }
        )
    )
    out = sync.auto_update(runner=r)
    assert out.changed is True
    assert "fast-forwarded 3" in out.line
    # it fetched the branch's upstream, then merged --ff-only
    assert ["fetch", "origin", "main"] in r.calls  # type: ignore[attr-defined]
    assert ["merge", "--ff-only", "@{u}"] in r.calls  # type: ignore[attr-defined]


def test_auto_update_noop_when_up_to_date() -> None:
    r = _seq_runner(_on_main({"rev-list": (0, "0\t0\n")}))
    out = sync.auto_update(runner=r)
    assert out.changed is False
    assert "up to date" in out.line
    assert ["merge", "--ff-only", "@{u}"] not in r.calls  # type: ignore[attr-defined]


def test_auto_update_ahead_only_is_not_a_change() -> None:
    r = _seq_runner(_on_main({"rev-list": (0, "0\t2\n")}))  # 0 behind, 2 ahead
    out = sync.auto_update(runner=r)
    assert out.changed is False
    assert "ahead" in out.line
    assert ["merge", "--ff-only", "@{u}"] not in r.calls  # type: ignore[attr-defined]


def test_auto_update_skips_when_dirty() -> None:
    r = _seq_runner(
        _on_main({"rev-list": (0, "2\t0\n"), "status": (0, " M kernel/x.py\n")})
    )
    out = sync.auto_update(runner=r)
    assert out.changed is False
    assert "dirty" in out.line
    assert ["merge", "--ff-only", "@{u}"] not in r.calls  # type: ignore[attr-defined]


def test_auto_update_refuses_non_fast_forward() -> None:
    r = _seq_runner(
        _on_main(
            {
                "rev-list": (0, "2\t1\n"),  # diverged
                "status": (0, ""),
                "merge": (1, "fatal: Not possible to fast-forward"),
            }
        )
    )
    out = sync.auto_update(runner=r)
    assert out.changed is False
    assert "not a fast-forward" in out.line


def test_auto_update_skips_detached_head_without_fetching() -> None:
    r = _seq_runner({"abbrev-ref HEAD": (0, "HEAD\n")})  # detached, no upstream
    out = sync.auto_update(runner=r)
    assert out.changed is False
    assert "skipping" in out.line
    # never reaches the network when there's nothing to track
    assert all(c[0] != "fetch" for c in r.calls)  # type: ignore[attr-defined]
