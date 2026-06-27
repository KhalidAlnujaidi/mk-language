"""Layered command-permission rulesets (CodeWhale Tier-2 harvest).

Ported from CodeWhale's `execpolicy` ruleset layering (`RulesetLayer` +
`ToolAskRule`): permission rules carry a *layer* (builtin < agent < user) and an
*action* (allow / ask / deny), and a concrete command resolves against them by a
deterministic precedence.

This gives the ASK level introduced by :mod:`products.agent.command_safety` an
*override surface*: the BUILTIN baseline (what `command_safety.assess` decided)
can be tightened or relaxed by an AGENT default or a USER rule — e.g. a user who
trusts `git push --force` in their own repo writes one ALLOW rule, or an operator
denies `npm publish` outright.

Precedence (deterministic, thesis #1 — no model):
  1. **Highest layer wins.** A USER rule overrides an AGENT rule overrides the
     BUILTIN baseline. The human operator is sovereign over the agent.
  2. **Within a layer, most specific wins** (a rule naming a command prefix beats
     a blanket rule; a longer prefix beats a shorter one).
  3. **On an exact tie, the safer action wins** (DENY > ASK > ALLOW) — fail-CLOSED
     (thesis #2).

One hard floor (thesis #2 / hard-truth #1 — honest limits): a **catastrophic
BUILTIN DENY** (`sudo`, pipe-to-shell, fork bomb, device wipe, root/home
`rm -rf`) is NOT relaxable by a rule. The ruleset governs the ASK/ALLOW space and
may *add* denials; it cannot turn a fork bomb into an allowed command.
"""

from __future__ import annotations

import shlex
import tomllib
from dataclasses import dataclass
from enum import Enum, IntEnum
from pathlib import Path

from products.agent import command_safety


class Layer(IntEnum):
    """Who set a rule. Higher ordinal overrides lower (user beats agent beats
    the builtin baseline)."""

    BUILTIN = 0
    AGENT = 1
    USER = 2


class Action(Enum):
    """What a rule decides for a command."""

    ALLOW = "allow"
    ASK = "ask"
    DENY = "deny"

    @property
    def priority(self) -> int:
        """Safer actions sort higher for the same-layer/same-specificity tiebreak
        (DENY > ASK > ALLOW) — fail-CLOSED."""
        return {Action.ALLOW: 0, Action.ASK: 1, Action.DENY: 2}[self]


# command_safety baseline (a Level) → the equivalent Action.
_LEVEL_TO_ACTION: dict[command_safety.Level, Action] = {
    command_safety.Level.SAFE: Action.ALLOW,
    command_safety.Level.ASK: Action.ASK,
    command_safety.Level.DENY: Action.DENY,
}


def level_to_action(level: command_safety.Level) -> Action:
    """Map a :class:`command_safety.Level` baseline to an :class:`Action`."""
    return _LEVEL_TO_ACTION[level]


def _command_matches(prefix: str, command: str) -> bool:
    """Arity-aware test: does *command* fall under the rule *prefix*?

    Reuses :func:`command_safety.classify`, so a rule for ``git push`` matches
    ``git push -f origin`` (flags don't count toward arity) but never
    ``git status``. Falls back to a word-boundary prefix match for prefixes not
    in the arity table (so ``ls`` matches ``ls -la`` but not ``lsof``)."""
    prefix_norm = " ".join(prefix.lower().split())
    try:
        tokens = shlex.split(command, comments=False, posix=True)
    except ValueError:
        return False
    if command_safety.classify(tokens) == prefix_norm:
        return True
    command_norm = " ".join(t.lower() for t in tokens)
    return command_norm == prefix_norm or command_norm.startswith(prefix_norm + " ")


@dataclass(frozen=True)
class Rule:
    """One permission rule. ``tool``/``command_prefix`` of ``None`` mean "any"."""

    layer: Layer
    action: Action
    tool: str | None = None
    command_prefix: str | None = None

    def matches(self, tool: str, command: str) -> bool:
        """True when this rule applies to *tool* running *command*."""
        if self.tool is not None and self.tool != tool:
            return False
        return self.command_prefix is None or _command_matches(
            self.command_prefix, command
        )

    @property
    def specificity(self) -> int:
        """How specific this rule is — more constraints / longer prefix win
        within a layer. A bare catch-all scores 0."""
        score = 0
        if self.tool is not None:
            score += 1
        if self.command_prefix is not None:
            score += 1 + len(self.command_prefix)
        return score


@dataclass(frozen=True)
class Decision:
    """The resolved action for a command, with the *rule* that decided it
    (``None`` when the builtin baseline stood) and a human-readable *reason*."""

    action: Action
    reason: str
    rule: Rule | None


@dataclass(frozen=True)
class Ruleset:
    """An ordered set of layered rules. Resolution is pure and deterministic."""

    rules: tuple[Rule, ...] = ()

    def resolve(
        self, *, tool: str, command: str, baseline: Action
    ) -> Decision:
        """Resolve the effective action for *tool* running *command*.

        *baseline* is the BUILTIN verdict (from ``command_safety``). A
        catastrophic baseline DENY is a hard floor — no rule can relax it.
        Otherwise the highest-layer, most-specific matching rule wins (DENY >
        ASK > ALLOW on a tie); with no match the baseline stands.
        """
        if baseline is Action.DENY:
            return Decision(Action.DENY, "builtin: catastrophic command", None)

        matching = [r for r in self.rules if r.matches(tool, command)]
        if not matching:
            return Decision(baseline, "builtin baseline (no rule matched)", None)

        winner = max(
            matching,
            key=lambda r: (int(r.layer), r.specificity, r.action.priority),
        )
        return Decision(
            winner.action,
            f"{winner.layer.name.lower()} rule "
            f"({winner.command_prefix or '*'} → {winner.action.value})",
            winner,
        )


def from_dicts(raw: list[dict[str, object]]) -> Ruleset:
    """Build a :class:`Ruleset` from a list of plain dicts (e.g. parsed TOML).

    Strict by design (fail-CLOSED at config time, not silently): an unknown
    layer/action or a missing required field raises ``ValueError`` so a typo in a
    permission file is caught loudly rather than dropping a DENY rule open.
    """
    rules: list[Rule] = []
    for i, entry in enumerate(raw):
        try:
            layer = Layer[str(entry["layer"]).upper()]
            action = Action(str(entry["action"]).lower())
        except (KeyError, ValueError) as exc:
            raise ValueError(f"permission rule #{i}: bad layer/action ({exc})") from exc
        tool_raw = entry.get("tool")
        cmd_raw = entry.get("command", entry.get("command_prefix"))
        rules.append(
            Rule(
                layer=layer,
                action=action,
                tool=str(tool_raw) if tool_raw is not None else None,
                command_prefix=str(cmd_raw) if cmd_raw is not None else None,
            )
        )
    return Ruleset(tuple(rules))


def load_ruleset(path: Path) -> Ruleset:
    """Load a permission ruleset from a TOML file, fail-SOFT on absence.

    A missing file yields an empty ruleset (baseline-only behaviour — no
    regression). A present-but-malformed file raises (fail-CLOSED: a broken
    permission file is an operator error worth surfacing, not silently ignoring).

    Expected shape::

        [[rules]]
        layer = "user"            # builtin | agent | user
        action = "allow"          # allow | ask | deny
        tool = "run_bash"         # optional — omit for any tool
        command = "git push"      # optional — omit for any command
    """
    if not path.exists():
        return Ruleset()
    with path.open("rb") as f:
        data = tomllib.load(f)
    raw_rules = data.get("rules", [])
    if not isinstance(raw_rules, list):
        raise ValueError(f"{path}: [[rules]] must be an array of tables")
    dicts: list[dict[str, object]] = [r for r in raw_rules if isinstance(r, dict)]
    return from_dicts(dicts)
