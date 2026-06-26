"""Capability registry — turn external skill/agent/MCP assets into registered tools.

Rule Zero, applied to the ECC corpus under ``cheatcodes/``: instead of copying
441 skills + 67 agents + MCP configs into the framework, we **load and register**
them as a queryable catalog of :class:`Capability` records. The agent runtime
(``products/agent/``, next phase) consumes this registry to expose skills as
prompt-selectable capabilities, agents as sub-agent descriptors, and MCP servers
as executable tools — so the capabilities live *in the framework* as a live
registry, not as vendored bytes.

This module is the **catalog layer** only: it parses metadata, it does not run
anything. It is pure (stdlib-only, no kernel/daemon imports) and **fail-soft**
(thesis #2): a missing directory, unreadable file, or malformed frontmatter
yields fewer capabilities, never an exception.

Frontmatter is parsed by a deliberately minimal line scanner (thesis #1: this is
ground-truth text extraction, not fuzzy work) so the loader needs no YAML
dependency — it reads only the top-level ``key: value`` pairs it cares about.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, cast

#: The kinds of capability the registry knows about. Open by convention —
#: callers may register other kinds; nothing here hardcodes a closed set.
SKILL = "skill"
COMMAND = "command"
AGENT = "agent"
MCP_SERVER = "mcp_server"


@dataclass(frozen=True)
class Capability:
    """One registered capability harvested from an external asset.

    ``extra`` carries kind-specific metadata (an agent's ``model``/``tools``, an
    MCP server's ``command``/``args``) without forcing a fixed schema — kinds and
    their fields stay appendable.
    """

    name: str
    kind: str
    description: str
    source: str  # file path (skill/agent) or server key (mcp)
    extra: dict[str, str] = field(default_factory=dict[str, str])


def _safe_read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""


def _frontmatter(text: str) -> dict[str, str]:
    """Extract top-level ``key: value`` pairs from a leading ``---`` block.

    Intentionally minimal: indented (nested) lines such as a ``metadata:`` block
    are skipped, and surrounding quotes are stripped. Returns ``{}`` when there is
    no frontmatter, so callers fall back to filename-derived names.
    """
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}
    out: dict[str, str] = {}
    for line in lines[1:]:
        if line.strip() == "---":
            break
        if not line or line[0] in (" ", "\t"):
            continue  # nested/indented value (e.g. the metadata: sub-block)
        key, sep, val = line.partition(":")
        if not sep:
            continue
        out[key.strip()] = val.strip().strip('"').strip("'")
    return out


def load_skills(skills_dir: Path) -> tuple[Capability, ...]:
    """Register every ``<skill>/SKILL.md`` under *skills_dir* as a skill capability."""
    if not skills_dir.is_dir():
        return ()
    caps: list[Capability] = []
    for skill_md in sorted(skills_dir.glob("*/SKILL.md")):
        fm = _frontmatter(_safe_read(skill_md))
        name = fm.get("name") or skill_md.parent.name
        caps.append(
            Capability(
                name=name,
                kind=SKILL,
                description=fm.get("description", ""),
                source=str(skill_md),
            )
        )
    return tuple(caps)


def load_commands(commands_dir: Path) -> tuple[Capability, ...]:
    """Register every ``*.md`` under *commands_dir* as a command capability.

    Commands are slash-command playbooks; the name is the filename stem (their
    frontmatter carries ``description`` + ``argument-hint``, not ``name``)."""
    if not commands_dir.is_dir():
        return ()
    caps: list[Capability] = []
    for md in sorted(commands_dir.glob("*.md")):
        fm = _frontmatter(_safe_read(md))
        extra = {"argument-hint": fm["argument-hint"]} if "argument-hint" in fm else {}
        caps.append(
            Capability(
                name=fm.get("name") or md.stem,
                kind=COMMAND,
                description=fm.get("description", ""),
                source=str(md),
                extra=extra,
            )
        )
    return tuple(caps)


def load_agents(agents_dir: Path) -> tuple[Capability, ...]:
    """Register every ``*.md`` under *agents_dir* as an agent capability."""
    if not agents_dir.is_dir():
        return ()
    caps: list[Capability] = []
    for md in sorted(agents_dir.glob("*.md")):
        fm = _frontmatter(_safe_read(md))
        name = fm.get("name") or md.stem
        extra: dict[str, str] = {}
        for k in ("model", "tools"):
            if k in fm:
                extra[k] = fm[k]
        caps.append(
            Capability(
                name=name,
                kind=AGENT,
                description=fm.get("description", ""),
                source=str(md),
                extra=extra,
            )
        )
    return tuple(caps)


def load_mcp(config_path: Path) -> tuple[Capability, ...]:
    """Register each entry in an MCP ``mcpServers`` config as a capability."""
    if not config_path.is_file():
        return ()
    try:
        raw: Any = json.loads(config_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return ()
    if not isinstance(raw, dict):
        return ()
    servers: Any = cast("dict[str, Any]", raw).get("mcpServers")
    if not isinstance(servers, dict):
        return ()
    caps: list[Capability] = []
    for key, spec in cast("dict[str, Any]", servers).items():
        if not isinstance(spec, dict):
            continue
        spec_d = cast("dict[str, Any]", spec)
        extra = {
            "command": str(spec_d.get("command", "")),
            "args": json.dumps(spec_d.get("args", [])),
        }
        caps.append(
            Capability(
                name=str(key),
                kind=MCP_SERVER,
                description=str(spec_d.get("description", "")),
                source=str(key),
                extra=extra,
            )
        )
    return tuple(caps)


@dataclass(frozen=True)
class CapabilityRegistry:
    """An aggregated, queryable catalog of registered capabilities."""

    capabilities: tuple[Capability, ...] = ()

    @classmethod
    def from_ecc(cls, ecc_dir: Path) -> CapabilityRegistry:
        """Build a registry from an ECC bundle (skills + commands + agents + MCP).
        Fail-soft: absent sub-paths simply contribute nothing."""
        return cls(
            (
                *load_skills(ecc_dir / "skills"),
                *load_commands(ecc_dir / "commands"),
                *load_agents(ecc_dir / "agents"),
                *load_mcp(ecc_dir / "mcp-configs" / "mcp-servers.json"),
            )
        )

    @classmethod
    def from_claude_dir(cls, claude_dir: Path) -> CapabilityRegistry:
        """Build a registry from a harvested ``.claude/`` directory — the full
        committed corpus the agent discovers: skills + commands + agents + MCP
        servers. Fail-soft: any absent sub-path contributes nothing."""
        return cls(
            (
                *load_skills(claude_dir / "skills"),
                *load_commands(claude_dir / "commands"),
                *load_agents(claude_dir / "agents"),
                *load_mcp(claude_dir / "mcp-servers.json"),
            )
        )

    def by_kind(self, kind: str) -> tuple[Capability, ...]:
        return tuple(c for c in self.capabilities if c.kind == kind)

    def get(self, name: str) -> Capability | None:
        return next((c for c in self.capabilities if c.name == name), None)

    def __len__(self) -> int:
        return len(self.capabilities)
