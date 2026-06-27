"""Protected-rail guard — the agent may not overwrite kinox's own rails.

Closes hard truth #1 for the agent threat model. ``alignment/`` (the constitution
and the operating axioms) and ``next.md`` (working memory) are the files governance
*rests on* — so an agent must not be able to rewrite them mid-task. This is an
in-process, fail-CLOSED guard on the **write** vector (``write_file`` and a
``run_bash`` mutation/redirection); it is the same enforcement layer as the scope
wall and, like it, is not bypassable through the agent's own tools.

What it does NOT do, stated honestly (the constitution's honesty rail): READS are
always allowed — an agent must be able to read the axioms it follows. And this is
*process-level*, not kernel immutability: a write that never routes through the
guard (or a non-agent process) is not stopped here. For a guarantee against those,
``chattr +i`` / a read-only bind mount on ``alignment/`` is the OS-level option.

A deliberate human edit of the rails is the documented **recovery path**: set
``KINOX_UNLOCK_RAILS=1`` for that session and the guard stands down. The default is
locked, so the rails are protected unless an operator explicitly opts in.
"""

from __future__ import annotations

import json
import os
import shlex
from collections.abc import Callable
from pathlib import Path

from kernel.jsonutil import as_dict

Guard = Callable[[str, str], "str | None"]

#: The files governance rests on — protected from agent writes by default.
PROTECTED_RAILS: tuple[str, ...] = ("alignment", "next.md")

#: ``KINOX_UNLOCK_RAILS`` values (case-insensitive) that lift the protection.
_UNLOCK: frozenset[str] = frozenset({"1", "true", "yes", "on"})

#: Shell base commands that mutate a file in place (so a rail named as their arg is
#: a write, not a read). A bare reader (``cat``/``grep``/``less``) is NOT here, so
#: reading a rail through the shell stays allowed.
_MUTATORS: frozenset[str] = frozenset({
    "rm", "mv", "cp", "dd", "tee", "truncate", "install", "ln", "chmod", "chown",
    "sed",
})


def _rails_unlocked() -> bool:
    """True if the operator deliberately unlocked rail edits for this session."""
    return os.environ.get("KINOX_UNLOCK_RAILS", "").strip().lower() in _UNLOCK


def _rail_hit(path: str, root: Path) -> bool:
    """True if *path* (relative to *root*) resolves at or under a protected rail."""
    try:
        p = (root / path).resolve()
    except (ValueError, OSError):
        return False
    for rail in PROTECTED_RAILS:
        r = (root / rail).resolve()
        if p == r or r in p.parents:
            return True
    return False


def rail_write_reason(
    path: str, root: Path, *, unlocked: bool | None = None
) -> str | None:
    """Why a WRITE to *path* is refused as a protected rail — or ``None``.

    The single source of truth shared by the guard (which refuses) and the eval
    executor (which annotates), so the two can never disagree (thesis #1). The
    message names the rail and uses the words the ``refused`` checker recognises.
    """
    if (_rails_unlocked() if unlocked is None else unlocked):
        return None
    if _rail_hit(path, root):
        return (
            f"{path!r} is a protected rail (kinox's constitution/axioms or working "
            "memory) — write refused; set KINOX_UNLOCK_RAILS=1 to edit it deliberately"
        )
    return None


def rail_bash_reason(
    command: str, root: Path, *, unlocked: bool | None = None
) -> str | None:
    """Why a ``run_bash`` *command* that would MUTATE a protected rail is refused.

    Only fires when the command writes — a redirection (``>``/``>>``) or an
    in-place mutator (``rm``/``sed``/``tee``/…). A pure read of a rail
    (``cat alignment/AXIOMS.md``) is allowed, so the axioms stay readable.
    """
    if (_rails_unlocked() if unlocked is None else unlocked):
        return None
    try:
        tokens = shlex.split(command, comments=False, posix=True)
    except ValueError:
        return None  # the path-escape guard already refuses unparseable commands
    if not tokens:
        return None
    base = tokens[0].lower().rsplit("/", 1)[-1]
    redirects = any(t == ">" or t == ">>" or t.startswith((">", ">>")) for t in tokens)
    if not (redirects or base in _MUTATORS):
        return None  # a read of a rail is fine
    # The command writes — any token that resolves onto a rail is the write target
    # (flags and the base command resolve elsewhere, so they never match a rail).
    for tok in tokens:
        reason = rail_write_reason(tok, root, unlocked=False)
        if reason is not None:
            return reason
    return None


def protected_rails_guard(root: Path) -> Guard:
    """A composable pre-dispatch guard that refuses agent WRITES to the rails.

    Compose it with :func:`~products.agent.tools.project_root_guard` (via
    ``combine_guards``) so the rail protection holds alongside the root jail and
    scope wall. Fail-CLOSED; reads pass; ``KINOX_UNLOCK_RAILS=1`` stands it down.
    """
    root_p = Path(root)

    def guard(name: str, args_json: str) -> str | None:
        try:
            parsed: object = json.loads(args_json) if args_json else {}
        except json.JSONDecodeError:
            return None  # malformed args degrade to a fail-soft dispatch error
        args = as_dict(parsed)
        if name == "write_file":
            return rail_write_reason(str(args.get("path", "")), root_p)
        if name == "run_bash":
            return rail_bash_reason(str(args.get("command", "")), root_p)
        return None

    return guard
