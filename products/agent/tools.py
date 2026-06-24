"""Agent tools — the registry the loop dispatches to (vision §5, agent phase).

A :class:`Tool` is a stable name + JSON-schema input + a handler that returns a
string observation. :class:`ToolRegistry` turns a set of tools into (a) the
OpenAI ``tools`` schema the model sees and (b) a fail-soft dispatcher the loop
calls. This mirrors the harvested ``agent-harness-construction`` guidance: stable
explicit names, schema-first inputs, deterministic string output.

The genuine reuse (Rule Zero / thesis #1): tool *discovery* is the kinox skill
corpus. ``find_skill`` / ``load_skill`` are backed by the
:class:`~products.capabilities.registry.CapabilityRegistry`, so every skill added
under ``.claude/skills/`` widens what the agent can pull in — the positive
feedback loop (more skills → more capable agent) with no code change.

Pure logic: no TTY, no model. Filesystem tools are sandboxed to a *root* so a
runaway agent cannot read or write outside the scope it was given (thesis #2 —
the guard fails CLOSED on a path that escapes the root).
"""

from __future__ import annotations

import json
import subprocess
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from kernel.jsonutil import as_dict

from products.capabilities.registry import SKILL, CapabilityRegistry

#: A tool handler maps validated arguments to a string observation.
Handler = Callable[[dict[str, object]], str]


@dataclass(frozen=True)
class Tool:
    """One registered tool: a stable name, a description the model reads, a JSON
    schema for its arguments, and a handler returning a string observation."""

    name: str
    description: str
    parameters: dict[str, object]
    handler: Handler

    def schema(self) -> dict[str, object]:
        """The OpenAI ``tools`` entry for this tool."""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }


@dataclass
class ToolRegistry:
    """A name→tool table that emits an OpenAI tool schema and dispatches calls.

    Dispatch is **fail-soft** (thesis #2): an unknown tool, bad arguments, or a
    handler exception becomes an ``(error: …)`` observation string the model can
    read and recover from — the loop never crashes on a tool failure.
    """

    tools: dict[str, Tool] = field(default_factory=dict[str, Tool])

    def register(self, tool: Tool) -> None:
        self.tools[tool.name] = tool

    def schemas(self) -> list[dict[str, object]]:
        """The full OpenAI ``tools`` array to send with the request."""
        return [t.schema() for t in self.tools.values()]

    def dispatch(self, name: str, arguments: str | dict[str, object]) -> str:
        """Run tool *name* with *arguments* (a JSON string or a dict).

        Returns the observation string. Never raises — every failure mode maps to
        an ``(error: …)`` string so the agent can see it and adapt.
        """
        tool = self.tools.get(name)
        if tool is None:
            return f"(error: unknown tool {name!r})"
        try:
            parsed: object = (
                json.loads(arguments) if isinstance(arguments, str) else arguments
            )
        except json.JSONDecodeError as exc:
            return f"(error: tool {name!r} bad JSON arguments: {exc})"
        # ``as_dict`` coerces to ``dict[str, object]`` (``{}`` for a non-object),
        # so a malformed argument shape degrades to a tool-level error rather
        # than crashing — fail-soft (thesis #2).
        try:
            return tool.handler(as_dict(parsed))
        except Exception as exc:  # fail-soft: surface, never crash the loop
            return f"(tool error in {name!r}: {exc})"


# --- Built-in tools ----------------------------------------------------------


def _within(root: Path, target: str) -> Path | None:
    """Resolve *target* under *root*; return ``None`` if it escapes the root.

    The guard fails CLOSED (thesis #2): a path that resolves outside the scope is
    refused rather than followed.
    """
    try:
        p = (root / target).resolve()
        p.relative_to(root.resolve())
        return p
    except (ValueError, OSError):
        return None


def filesystem_tools(root: Path) -> list[Tool]:
    """Read-only filesystem tools sandboxed to *root* — the agent's eyes."""

    def read_file(args: dict[str, object]) -> str:
        p = _within(root, str(args.get("path", "")))
        if p is None:
            return "(error: path escapes the allowed root)"
        if not p.is_file():
            return f"(error: not a file: {args.get('path')})"
        text = p.read_text(encoding="utf-8", errors="replace")
        return text if len(text) <= 8000 else text[:8000] + "\n…(truncated)"

    def list_dir(args: dict[str, object]) -> str:
        p = _within(root, str(args.get("path", ".")))
        if p is None:
            return "(error: path escapes the allowed root)"
        if not p.is_dir():
            return f"(error: not a directory: {args.get('path')})"
        entries = sorted(
            f"{e.name}/" if e.is_dir() else e.name for e in p.iterdir()
        )
        return "\n".join(entries) if entries else "(empty)"

    return [
        Tool(
            name="read_file",
            description=(
                "Read a UTF-8 text file under the working root. Returns its "
                "contents (truncated at 8000 chars)."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Path relative to the working root.",
                    }
                },
                "required": ["path"],
            },
            handler=read_file,
        ),
        Tool(
            name="list_dir",
            description=(
                "List the entries of a directory under the working root. "
                "Directories end with '/'."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Directory path relative to the root "
                        "(default '.').",
                    }
                },
                "required": [],
            },
            handler=list_dir,
        ),
    ]


def bash_tool(root: Path, *, timeout_s: float = 30.0) -> Tool:
    """A guarded shell tool — the agent's hands. HIGH RISK.

    Runs in *root* with a timeout. This is the tool a pre-dispatch guard (thesis
    #2, fail-CLOSED) should gate hardest; the loop passes every call through its
    guard before this handler ever runs.
    """

    def run_bash(args: dict[str, object]) -> str:
        command = str(args.get("command", "")).strip()
        if not command:
            return "(error: empty command)"
        try:
            proc = subprocess.run(  # noqa: S602 — guarded agent tool, sandboxed to root
                command,
                shell=True,
                cwd=str(root),
                capture_output=True,
                text=True,
                timeout=timeout_s,
            )
        except subprocess.TimeoutExpired:
            return f"(error: command timed out after {timeout_s}s)"
        out = (proc.stdout or "") + (proc.stderr or "")
        out = out if len(out) <= 8000 else out[:8000] + "\n…(truncated)"
        return f"exit={proc.returncode}\n{out}".rstrip()

    return Tool(
        name="run_bash",
        description=(
            "Run a shell command in the working root and return its exit code "
            "and combined stdout/stderr."
        ),
        parameters={
            "type": "object",
            "properties": {
                "command": {
                    "type": "string",
                    "description": "The shell command to run.",
                }
            },
            "required": ["command"],
        },
        handler=run_bash,
    )


def skill_tools(registry: CapabilityRegistry) -> list[Tool]:
    """The skill bridge — the positive feedback loop (vision §0, Rule Zero).

    ``find_skill`` searches the kinox skill corpus by substring over name +
    description (thesis #1: ground-truth text match, no model); ``load_skill``
    returns a skill's full instructions so the agent can follow them. Every skill
    added under ``.claude/skills/`` is automatically discoverable — capability
    grows with the corpus, not with code.
    """
    skills = registry.by_kind(SKILL)

    def find_skill(args: dict[str, object]) -> str:
        query = str(args.get("query", "")).lower().strip()
        if not query:
            return "(error: empty query)"
        hits = [
            c
            for c in skills
            if query in c.name.lower() or query in c.description.lower()
        ]
        if not hits:
            return f"(no skill matches {query!r} among {len(skills)} skills)"
        lines = [f"- {c.name}: {c.description[:160]}" for c in hits[:15]]
        more = f"\n…and {len(hits) - 15} more" if len(hits) > 15 else ""
        return f"{len(hits)} match(es):\n" + "\n".join(lines) + more

    def load_skill(args: dict[str, object]) -> str:
        name = str(args.get("name", "")).strip()
        cap = registry.get(name)
        if cap is None or cap.kind != SKILL:
            return f"(error: no skill named {name!r} — use find_skill first)"
        text = Path(cap.source).read_text(encoding="utf-8", errors="replace")
        return text if len(text) <= 12000 else text[:12000] + "\n…(truncated)"

    return [
        Tool(
            name="find_skill",
            description=(
                "Search the kinox skill corpus for skills whose name or "
                "description matches a query. Use this BEFORE attempting an "
                "unfamiliar task — a skill may already encode how to do it."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Keywords to match against skill names "
                        "and descriptions.",
                    }
                },
                "required": ["query"],
            },
            handler=find_skill,
        ),
        Tool(
            name="load_skill",
            description=(
                "Load a skill's full instructions by exact name (from "
                "find_skill) and follow them."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "name": {
                        "type": "string",
                        "description": "Exact skill name from find_skill.",
                    }
                },
                "required": ["name"],
            },
            handler=load_skill,
        ),
    ]


def default_registry(
    root: Path,
    *,
    skills: CapabilityRegistry | None = None,
    allow_bash: bool = False,
) -> ToolRegistry:
    """Assemble the standard agent toolset: filesystem + skill bridge, plus the
    guarded ``run_bash`` only when *allow_bash* is set (fail-CLOSED default)."""
    reg = ToolRegistry()
    for t in filesystem_tools(root):
        reg.register(t)
    if skills is not None:
        for t in skill_tools(skills):
            reg.register(t)
    if allow_bash:
        reg.register(bash_tool(root))
    return reg
