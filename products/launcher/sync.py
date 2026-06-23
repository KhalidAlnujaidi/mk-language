"""Startup git-sync: fetch + notify, and a safe `kx update` (design 2026-06-23).

The framework checks GitHub on entry and tells you where you stand relative to
``origin/main`` — it never blind-pulls. `update()` fast-forwards ONLY when you're
behind AND the tree is clean AND it's a fast-forward; otherwise it reports and
leaves the tree untouched. All git access goes through an injectable ``runner``
so the logic is testable offline.
"""

from __future__ import annotations

import subprocess
from collections.abc import Callable
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
