"""Startup git-sync: fetch + notify, a safe `kx update`, and launch-time
self-upgrade (design 2026-06-23, auto-update 2026-06-27).

The framework checks GitHub on entry and tells you where you stand relative to
``origin/main`` — it never blind-pulls. `update()` fast-forwards ONLY when you're
behind AND the tree is clean AND it's a fast-forward; otherwise it reports and
leaves the tree untouched. `auto_update()` is the launch-time variant: it
fast-forwards the *checked-out* branch to its own upstream under the same safety
rules, so every `kx` invocation runs the latest code (kx loads straight from the
working tree). All git access goes through an injectable ``runner`` so the logic
is testable offline.
"""

from __future__ import annotations

import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

#: Run a git subcommand (args after `git`), return (exit_code, stdout).
GitRunner = Callable[[list[str]], "tuple[int, str]"]

_REPO = Path(__file__).resolve().parents[2]


def _real_runner(args: list[str]) -> tuple[int, str]:
    """Run `git <args>` in the repo, fail-soft, short timeout (network-safe)."""
    try:
        proc = subprocess.run(
            ["git", *args],
            cwd=_REPO,
            capture_output=True,
            text=True,
            timeout=15,
        )
        return proc.returncode, proc.stdout
    except Exception:
        return 1, ""


def ahead_behind(*, runner: GitRunner = _real_runner) -> tuple[int, int] | None:
    """Return (ahead, behind) of local main vs origin/main, or None on error."""
    rc, out = runner(["rev-list", "--left-right", "--count", "origin/main...main"])
    if rc != 0:
        return None
    parts = out.split()
    if len(parts) != 2 or not all(p.isdigit() for p in parts):
        return None
    behind, ahead = int(parts[0]), int(parts[1])  # left=origin-only, right=local-only
    return ahead, behind


def status_line(ab: tuple[int, int] | None) -> str:
    """One-line human status for the startup banner."""
    if ab is None:
        return "kinox sync: couldn't reach origin (offline?) — continuing"
    ahead, behind = ab
    if ahead == 0 and behind == 0:
        return "kinox sync: up to date with origin/main ✓"
    notes: list[str] = []
    if behind:
        notes.append(f"{behind} behind — run `kx update` to pull")
    if ahead:
        notes.append(f"{ahead} ahead (unpushed)")
    return "kinox sync: " + "; ".join(notes)


def _is_clean(*, runner: GitRunner) -> bool:
    rc, out = runner(["status", "--porcelain"])
    return rc == 0 and out.strip() == ""


def startup_status(*, runner: GitRunner = _real_runner) -> str:
    """Best-effort fetch, then return the status line. Never raises, never pulls."""
    runner(["fetch", "origin", "main"])
    return status_line(ahead_behind(runner=runner))


def update(*, runner: GitRunner = _real_runner) -> str:
    """`kx update`: fetch, then fast-forward only when behind, clean, and ff-able."""
    runner(["fetch", "origin", "main"])
    ab = ahead_behind(runner=runner)
    if ab is None:
        return "kx update: couldn't check origin (offline?)"
    ahead, behind = ab
    if behind == 0:
        tail = f" ({ahead} ahead, unpushed)" if ahead else ""
        return "kx update: already up to date" + tail
    if not _is_clean(runner=runner):
        return (
            f"kx update: {behind} behind, but the working tree is dirty"
            " — commit/stash first"
        )
    rc, out = runner(["pull", "--ff-only", "origin", "main"])
    if rc == 0:
        return f"kx update: pulled {behind} commit(s) (fast-forward)"
    return f"kx update: fast-forward failed (diverged?) — resolve manually:\n{out}"


@dataclass(frozen=True)
class SyncOutcome:
    """Result of a launch-time auto-update.

    ``changed`` says whether the working tree actually moved (so the caller can
    reload to run the new code); ``line`` is the one-line banner to show.
    """

    changed: bool
    line: str


def current_branch(*, runner: GitRunner = _real_runner) -> str | None:
    """The checked-out branch name, or None when detached / on error."""
    rc, out = runner(["rev-parse", "--abbrev-ref", "HEAD"])
    name = out.strip()
    if rc != 0 or not name or name == "HEAD":  # error or detached HEAD
        return None
    return name


def upstream(*, runner: GitRunner = _real_runner) -> str | None:
    """The current branch's upstream (e.g. ``origin/main``), or None if unset."""
    rc, out = runner(["rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}"])
    name = out.strip()
    return name if rc == 0 and name else None


def auto_update(*, runner: GitRunner = _real_runner) -> SyncOutcome:
    """Launch-time self-upgrade: fast-forward the checked-out branch to upstream.

    Fetches the current branch's upstream, then fast-forwards ONLY when behind,
    clean, and a true fast-forward — never a merge or rebase, so committed or
    in-progress work is never lost or rewritten. Returns ``changed=True`` when
    the tree actually moved (the caller should then reload). Fail-soft: any
    unexpected git state leaves the tree untouched and is reported, never raised.
    """
    branch = current_branch(runner=runner)
    up = upstream(runner=runner)
    if branch is None or up is None:
        return SyncOutcome(
            False, "kinox sync: detached HEAD or no upstream — skipping auto-update"
        )
    remote, _, remote_branch = up.partition("/")
    if not remote_branch:  # malformed upstream ref
        return SyncOutcome(False, "kinox sync: can't parse upstream — skipping")
    runner(["fetch", remote, remote_branch])
    rc, out = runner(["rev-list", "--left-right", "--count", "@{u}...HEAD"])
    parts = out.split()
    if rc != 0 or len(parts) != 2 or not all(p.isdigit() for p in parts):
        return SyncOutcome(
            False, "kinox sync: couldn't compare with upstream (offline?) — continuing"
        )
    behind, ahead = int(parts[0]), int(parts[1])
    if behind == 0:
        tail = f" ({ahead} ahead, unpushed)" if ahead else ""
        return SyncOutcome(False, f"kinox sync: up to date with {up} ✓" + tail)
    if not _is_clean(runner=runner):
        return SyncOutcome(
            False,
            f"kinox sync: {behind} behind {up}, but the working tree is dirty"
            " — skipping auto-update (commit/stash, then `kx update`)",
        )
    rc, _ = runner(["merge", "--ff-only", "@{u}"])
    if rc == 0:
        return SyncOutcome(
            True,
            f"kinox sync: upgraded — fast-forwarded {behind} commit(s) from {up} ✓",
        )
    return SyncOutcome(
        False,
        f"kinox sync: {behind} behind {up} but not a fast-forward (diverged)"
        " — run `kx update` or resolve manually",
    )
