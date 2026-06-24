"""Hook registry and chain engine (Brick B — vision §5.2, §7.1).

Every hook declares its ``FailDirection`` (thesis #2): a CLOSED hook denies on
doubt and stops the chain; a SOFT hook passes through on doubt and the chain
continues. The runner absorbs SOFT errors and halts on CLOSED errors or denials.

Per-project configuration lives in ``projects/<name>/hooks.toml``::

    [hooks]
    pre_inference = ["groom", "ctx"]
    pre_tool_use = ["guard", "protected_files"]

``load_chain`` reads this file, resolves hook names against a *registry* of
known hooks (keyed by name), and returns a ``HookChain`` ready to run.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from pathlib import Path

from kernel.contracts import FailDirection

# ---------------------------------------------------------------------------
# Types
# ---------------------------------------------------------------------------

#: Hook input is a dict (flexible, matches the agent hook payload shape
#: and generalises to any hook kind without coupling to a specific schema).
HookInput = dict[str, object]

#: A hook handler: async, takes HookInput, returns HookResult.
HookHandler = Callable[[HookInput], Awaitable["HookResult"]]

#: A registry maps hook names (keys in hooks.toml) to their declarations.
HookRegistry = dict[str, "HookDecl"]


@dataclass(frozen=True)
class HookResult:
    """What a hook returned.

    ``decision`` is ``"allow"`` or ``"deny"``.  ``context_lines`` carry
    additive annotation for the agent (only meaningful on ``"allow"``).
    ``reason`` explains the denial.
    """

    decision: str
    context_lines: tuple[str, ...] = ()
    reason: str = ""

    @classmethod
    def allow(cls, lines: tuple[str, ...] = ()) -> HookResult:
        """The hook passes; optional context lines are injected."""
        return cls(decision="allow", context_lines=lines)

    @classmethod
    def deny(cls, reason: str) -> HookResult:
        """The hook blocks; *reason* is surfaced to the caller."""
        return cls(decision="deny", reason=reason)


@dataclass(frozen=True)
class HookDecl:
    """One hook declaration with its declared fail-direction (thesis #2)."""

    name: str
    kind: str
    fail_direction: FailDirection
    handler: HookHandler


@dataclass
class HookChain:
    """An ordered list of hooks to run for one hook kind.

    ``run`` executes hooks in order, respecting each hook's fail-direction:
    - A CLOSED hook that raises → chain halts with ``deny``.
    - A SOFT hook that raises → error is absorbed; chain continues.
    - Any hook that returns ``deny`` → chain halts immediately (regardless of
      fail-direction — a conscious deny is always final).
    """

    hooks: list[HookDecl] = field(default_factory=list)

    async def run(self, hook_input: HookInput) -> HookResult:
        """Execute every hook in order. Returns the accumulated result."""
        lines: list[str] = []
        for hook in self.hooks:
            try:
                result = await hook.handler(hook_input)
            except Exception:
                if hook.fail_direction == FailDirection.CLOSED:
                    return HookResult.deny(
                        f"hook {hook.name!r} failed closed"
                    )
                # SOFT: absorb the error and continue.
                continue

            if result.decision == "deny":
                return result  # conscious deny always stops the chain.

            lines.extend(result.context_lines)

        return HookResult.allow(tuple(lines))


# ---------------------------------------------------------------------------
# Per-project configuration
# ---------------------------------------------------------------------------


def load_chain(
    project_dir: Path, registry: HookRegistry, *, kind: str
) -> HookChain:
    """Read ``hooks.toml`` from *project_dir* and build a ``HookChain``.

    The TOML expects a ``[hooks]`` table with array-of-strings keys per hook
    kind.  Each name must be present in *registry*.

    Returns an empty chain when the config file is absent.
    """
    config_path = project_dir / "hooks.toml"
    if not config_path.exists():
        return HookChain()

    # Lazy import: toml is only needed when a config file actually exists.
    import tomllib

    raw = tomllib.loads(config_path.read_text(encoding="utf-8"))
    hooks_section = raw.get("hooks", {})
    if not isinstance(hooks_section, dict):
        return HookChain()

    names = hooks_section.get(kind)
    if not isinstance(names, list):
        return HookChain()

    decls: list[HookDecl] = []
    for name in names:
        if not isinstance(name, str):
            continue
        if name not in registry:
            raise KeyError(
                f"hook {name!r} in {config_path} is not registered"
            )
        decls.append(registry[name])

    return HookChain(hooks=decls)
