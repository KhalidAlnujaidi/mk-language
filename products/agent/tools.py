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
import re
import shlex
import subprocess
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

from kernel.jsonutil import as_dict

from products.capabilities.registry import MCP_SERVER, CapabilityRegistry

if TYPE_CHECKING:
    from daemon.mcp import MCPServer

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


#: Tokens whose mere presence can reach outside the project root (home / env-home
#: expansion resolves to an arbitrary location the lexical check below cannot see).
_HOME_EXPANSION = re.compile(r"(^|[\s=:(\"'])~|\$\{?HOME\b")


def _candidate_paths(token: str) -> list[str]:
    """Path-like strings inside one shell token (the token itself, and the value
    after an ``=`` for ``--flag=/path`` forms). Non-path tokens yield nothing."""
    parts = [token]
    if "=" in token:
        parts.append(token.split("=", 1)[1])
    return [
        p
        for p in parts
        if p == ".."
        or p.startswith(("/", "./", "../"))
        or "/" in p
    ]


def _bash_escape_reason(command: str, root: Path) -> str | None:
    """Why *command* would touch the filesystem outside *root* — or ``None``.

    A best-effort LEXICAL jail (thesis #2, fail-CLOSED): it refuses home/env-home
    expansion, absolute paths outside the root, and parent-traversal that escapes.
    It is NOT a kernel sandbox — it cannot see through ``$(...)`` substitution,
    here-docs, or env indirection. True containment needs OS user-namespaces
    (unavailable here: AppArmor restricts unprivileged userns), so this lexical
    guard is the governing layer, and it errs toward refusing.
    """
    if _HOME_EXPANSION.search(command):
        return "home-directory expansion (~ or $HOME) can reach outside the root"
    try:
        tokens = shlex.split(command, comments=False, posix=True)
    except ValueError:
        # Unbalanced quotes → cannot verify path safety → refuse (fail-CLOSED).
        return "command could not be parsed for path safety"
    for tok in tokens:
        for cand in _candidate_paths(tok):
            if _within(root, cand) is None:
                return f"path {cand!r} escapes the project root"
    return None


def project_root_guard(
    root: Path, *, deny_write_subpaths: tuple[str, ...] = ()
) -> Callable[[str, str], str | None]:
    """A pre-dispatch :data:`~products.agent.loop.Guard` that jails every tool to
    *root* — the governance the loop applies before a handler runs.

    Filesystem tools already self-jail via :func:`_within`; this adds the same
    boundary at the loop level (so an escape shows as a ``blocked`` trace event,
    auditable) and is the ONLY containment for ``run_bash``. Fails CLOSED on a
    detected escape; passes (returns ``None``) otherwise. Wiring this guard makes
    "the session resides only within its repository" the default for every
    project — framework, evolve, and admin sessions alike.

    *deny_write_subpaths* are directories (relative to *root*) that this scope may
    READ but not WRITE — ``write_file`` into them and ``run_bash`` referencing them
    are refused (fail-CLOSED). A **framework** scope passes ``("projects",)`` so it
    cannot write down into a project scope: the scope wall is bidirectional (a
    project already cannot reach up), which is what makes framework-and-project
    development safe to run in parallel without overlap.
    """
    root_p = Path(root)
    denied = [(root_p / s).resolve() for s in deny_write_subpaths]

    def _hits_denied(path: str) -> bool:
        try:
            p = (root_p / path).resolve()
        except (ValueError, OSError):
            return False
        return any(p == d or d in p.parents for d in denied)

    def guard(name: str, args_json: str) -> str | None:
        try:
            parsed: object = json.loads(args_json) if args_json else {}
        except json.JSONDecodeError:
            return None  # malformed args degrade to a fail-soft dispatch error
        args = as_dict(parsed)  # dict[str, object], {} for a non-object shape
        if name == "run_bash":
            command = str(args.get("command", ""))
            escape = _bash_escape_reason(command, root_p)
            if escape is not None:
                return escape
            if denied:
                try:
                    tokens = shlex.split(command, comments=False, posix=True)
                except ValueError:
                    return "command could not be parsed for scope-wall safety"
                for tok in tokens:
                    for cand in _candidate_paths(tok):
                        if _hits_denied(cand):
                            return (
                                f"path {cand!r} is in another scope (a project) — "
                                "this framework session may not write there"
                            )
            return None
        if name in ("read_file", "list_dir", "write_file"):
            default = "." if name == "list_dir" else ""
            path = str(args.get("path", default))
            if _within(root_p, path) is None:
                return f"path {path!r} escapes the project root"
            if name == "write_file" and _hits_denied(path):
                return (
                    f"path {path!r} is in another scope (a project) — this "
                    "framework session may not write there (use the project scope)"
                )
        return None

    return guard


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


def write_tools(root: Path) -> list[Tool]:
    """Write/overwrite filesystem tools sandboxed to *root* — the agent's hands
    for files. Together with ``run_bash`` they make an unrestricted in-scope
    coding agent; the ``_within`` guard still fails CLOSED outside the scope, so
    "unrestricted" means full power *within the working root*, escapable only via
    the (deliberately equally-powerful) shell."""

    def write_file(args: dict[str, object]) -> str:
        rel = str(args.get("path", ""))
        p = _within(root, rel)
        if p is None:
            return "(error: path escapes the allowed root)"
        content = args.get("content")
        if not isinstance(content, str):
            return "(error: 'content' must be a string)"
        try:
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(content, encoding="utf-8")
        except OSError as exc:
            return f"(error: {exc})"
        return f"wrote {len(content)} bytes to {rel}"

    return [
        Tool(
            name="write_file",
            description=(
                "Create or overwrite a UTF-8 text file under the working root "
                "with the given content (parent dirs are created). Use this to "
                "edit files — read_file first, then write the full new contents."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Path relative to the working root.",
                    },
                    "content": {
                        "type": "string",
                        "description": "Full new file contents.",
                    },
                },
                "required": ["path", "content"],
            },
            handler=write_file,
        ),
    ]


def bash_tool(root: Path, *, timeout_s: float = 30.0) -> Tool:
    """A guarded shell tool — the agent's hands. HIGH RISK.

    Runs in *root* with a timeout. Two layers of containment, defense-in-depth:
    a lexical pre-check (`_bash_escape_reason`, fail-CLOSED) that refuses obvious
    escapes, and — when the kernel supports it — a **Landlock** sandbox on the
    child that *physically* forbids writes outside the scope root (plus shared
    scratch), so a write that fools the lexical check (``$VAR``/``$(...)``
    indirection) is still denied by the OS. Landlock-absent systems fall back to
    the lexical layer alone (fail-soft at setup).
    """
    from products.agent.sandbox import write_jail_preexec

    preexec = write_jail_preexec(root)  # None when Landlock is unavailable

    def run_bash(args: dict[str, object]) -> str:
        command = str(args.get("command", "")).strip()
        if not command:
            return "(error: empty command)"
        # Self-jail (defense-in-depth): even with no loop-level guard wired, the
        # shell cannot read or write outside its root. Fails CLOSED (thesis #2).
        escape = _bash_escape_reason(command, root)
        if escape is not None:
            return (
                f"(blocked: {escape} — run_bash is jailed to the project root; "
                "operate only within it)"
            )
        try:
            proc = subprocess.run(  # noqa: S602 — guarded agent tool, sandboxed to root
                command,
                shell=True,
                cwd=str(root),
                capture_output=True,
                text=True,
                timeout=timeout_s,
                preexec_fn=preexec,  # Landlock write-jail (None → lexical only)
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
            "and combined stdout/stderr. The shell is jailed to the project root: "
            "commands that reference paths outside it (absolute paths, ~, ..) are "
            "refused. Use paths relative to the root."
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


# Word-overlap scoring for skill search — mirrors ``products/beacon/bible.py``'s
# deterministic retrieval (stdlib only, no model, no embeddings). Replicated here
# rather than imported to keep the dependency direction clean (beacon → agent, not
# the reverse). This is the deterministic recall layer for skill choice.
_SKILL_WORD = re.compile(r"[a-z0-9]+")
_SKILL_STOP = frozenset(
    # A flat stopword string reads clearer than a 40-item list literal here.
    "the a an and or of to in for on is are be with that this it as by from at "  # noqa: SIM905
    "which we you they i how what when where why can will into over under not no "
    "your their our its use using used".split()
)


def _skill_tokens(text: str) -> set[str]:
    return {
        w
        for w in _SKILL_WORD.findall(text.lower())
        if w not in _SKILL_STOP and len(w) > 2
    }


def skill_tools(registry: CapabilityRegistry) -> list[Tool]:
    """The capability bridge — the positive feedback loop (vision §0, Rule Zero).

    ``find_skill`` searches the WHOLE harvested corpus — skills, commands, and
    agent playbooks — ranking by word overlap over name + description (thesis #1:
    deterministic text match, no model), with an exact phrase counting as a strong
    signal. Ranked recall surfaces the on-topic capability even when no contiguous
    substring matches, so the agent loads the right skill instead of over-loading
    junk (less context rot). ``load_skill`` returns a capability's full
    instructions so the agent can follow them. Everything under ``.claude/`` is
    automatically discoverable — capability grows with the corpus, not with code.
    """
    caps = registry.capabilities

    def find_skill(args: dict[str, object]) -> str:
        raw = str(args.get("query", "")).strip()
        if not raw:
            return "(error: empty query)"
        query = raw.lower()
        q_tokens = _skill_tokens(query)
        scored: list[tuple[int, object]] = []
        for c in caps:
            score = len(q_tokens & _skill_tokens(f"{c.name} {c.description}"))
            if query in c.name.lower() or query in c.description.lower():
                score += 5  # exact phrase ranks above scattered token overlap
            if score > 0:
                scored.append((score, c))
        if not scored:
            return f"(no capability matches {raw!r} among {len(caps)} entries)"
        scored.sort(key=lambda sc: (-sc[0], sc[1].name))  # type: ignore[attr-defined]
        hits = [c for _, c in scored]
        lines = [f"- [{c.kind}] {c.name}: {c.description[:140]}" for c in hits[:20]]
        more = f"\n…and {len(hits) - 20} more" if len(hits) > 20 else ""
        return f"{len(hits)} match(es):\n" + "\n".join(lines) + more

    def load_skill(args: dict[str, object]) -> str:
        name = str(args.get("name", "")).strip()
        cap = registry.get(name)
        if cap is None:
            return f"(error: no capability named {name!r} — use find_skill first)"
        if cap.kind == MCP_SERVER:
            return (
                f"(mcp server {name!r}: {cap.description}. Configured in "
                ".claude/mcp-servers.json — not a file to read.)"
            )
        text = Path(cap.source).read_text(encoding="utf-8", errors="replace")
        return text if len(text) <= 12000 else text[:12000] + "\n…(truncated)"

    return [
        Tool(
            name="find_skill",
            description=(
                "Search the kinox capability corpus (skills, commands, and agent "
                "playbooks), ranked by relevance to your keywords. Use this BEFORE "
                "attempting an unfamiliar task — a skill/command/agent may already "
                "encode how to do it. Describe the task in a few words; the most "
                "relevant results come first. Results are tagged [skill] / "
                "[command] / [agent]."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Keywords to match against names and "
                        "descriptions across the corpus.",
                    }
                },
                "required": ["query"],
            },
            handler=find_skill,
        ),
        Tool(
            name="load_skill",
            description=(
                "Load a capability's full instructions by exact name (from "
                "find_skill) — a skill, command, or agent playbook — and follow them."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "name": {
                        "type": "string",
                        "description": "Exact capability name from find_skill.",
                    }
                },
                "required": ["name"],
            },
            handler=load_skill,
        ),
    ]


#: Started MCP servers, cached per config path so the agent loop does not respawn
#: them every turn. Populated lazily by :func:`mcp_tools`.
_MCP_CACHE: dict[str, list[MCPServer]] = {}


def _wrap_mcp_tool(server: object, spec: dict[str, object]) -> Tool:
    """Wrap one remote MCP tool *spec* as a kinox :class:`Tool` that dispatches to
    *server*. Named ``mcp__<server>__<tool>`` so it is unambiguous in the trace."""
    from daemon.mcp import MCPServer

    srv = server if isinstance(server, MCPServer) else None
    tool_name = str(spec.get("name", ""))
    schema: dict[str, object] = as_dict(spec.get("inputSchema"))
    if not schema:
        schema = {"type": "object", "properties": {}}

    def handler(args: dict[str, object]) -> str:
        if srv is None:
            return "(error: mcp server unavailable)"
        return srv.call(tool_name, args)

    label = srv.name if srv is not None else "mcp"
    return Tool(
        name=f"mcp__{label}__{tool_name}",
        description=str(spec.get("description", ""))[:500],
        parameters=schema,
        handler=handler,
    )


def mcp_tools(config_path: Path, *, max_servers: int = 8) -> list[Tool]:
    """Start the launchable MCP servers in *config_path* (once, cached) and return
    their remote tools as kinox Tools. Fail-soft: unlaunchable/dead servers
    contribute nothing, so the agent simply gets whatever is actually configured."""
    from daemon.mcp import load_server_specs

    key = str(config_path)
    servers = _MCP_CACHE.get(key)
    if servers is None:
        started: list[MCPServer] = []
        for spec in load_server_specs(config_path):
            if spec.launchable() and spec.start():
                started.append(spec)
            if len(started) >= max_servers:
                break
        _MCP_CACHE[key] = started
        servers = started
    tools: list[Tool] = []
    for srv in servers:
        for remote in srv.tools:
            tools.append(_wrap_mcp_tool(srv, remote))
    return tools


def default_registry(
    root: Path,
    *,
    skills: CapabilityRegistry | None = None,
    allow_bash: bool = False,
    allow_write: bool = False,
    mcp_config: Path | None = None,
) -> ToolRegistry:
    """Assemble the agent toolset: read-only filesystem + skill bridge, plus the
    high-risk ``write_file`` (when *allow_write*) and ``run_bash`` (when
    *allow_bash*), plus live MCP server tools (when *mcp_config* points at an
    ``mcpServers`` config). Write/exec are OFF by default (fail-CLOSED, thesis
    #2); a fully-trusted interactive session opts into both for an unrestricted
    in-scope coding agent."""
    reg = ToolRegistry()
    for t in filesystem_tools(root):
        reg.register(t)
    if allow_write:
        for t in write_tools(root):
            reg.register(t)
    if skills is not None:
        for t in skill_tools(skills):
            reg.register(t)
    if allow_bash:
        reg.register(bash_tool(root))
    if mcp_config is not None:
        for t in mcp_tools(mcp_config):
            reg.register(t)
    return reg
