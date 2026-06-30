"""MCP client — make Model Context Protocol servers *executable* by the agent.

Discovery (``products/capabilities``) catalogs MCP servers; this module *runs*
them. An :class:`MCPServer` spawns a server subprocess and speaks JSON-RPC 2.0
over stdio (newline-delimited, the MCP stdio transport): ``initialize`` →
``notifications/initialized`` → ``tools/list``, then ``tools/call`` per
invocation. Each remote tool is wrapped as a kinox :class:`~products.agent.tools.Tool`
named ``mcp__<server>__<tool>`` so the agent loop calls it like any other tool.

Dependency-light on purpose (the kinox ethos): a ~150-line stdio client, no SDK,
no pydantic/anyio. **Fail-soft** throughout (thesis #2): a server that is not
launchable (binary missing, placeholder credentials) or that never answers
simply contributes no tools — it never raises into the agent loop.

POSIX/stdio (``select`` on the child's pipe); kinox targets Linux.
"""

from __future__ import annotations

import contextlib
import json
import os
import select
import shutil
import subprocess
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

from kernel.jsonutil import as_dict

_PROTOCOL_VERSION = "2024-11-05"
_CLIENT_INFO = {"name": "kinox", "version": "0.1"}


@dataclass
class MCPServer:
    """One MCP server subprocess, spoken to over stdio JSON-RPC.

    Construct with the launch *command*/*args*/*env* (from an ``mcpServers``
    config entry), call :meth:`start` (handshake + ``tools/list``), then
    :meth:`call` per tool. :attr:`tools` holds the server's advertised tool specs
    after a successful start."""

    name: str
    command: str
    args: list[str] = field(default_factory=list[str])
    env: dict[str, str] = field(default_factory=dict[str, str])
    tools: list[dict[str, object]] = field(default_factory=list[dict[str, object]])
    _proc: subprocess.Popen[bytes] | None = None
    _buf: bytes = b""
    _id: int = 0
    _lock: threading.Lock = field(default_factory=threading.Lock)

    # --- lifecycle -----------------------------------------------------------

    def launchable(self) -> bool:
        """``True`` only if the command is on PATH and no env value is a
        placeholder (``YOUR_…`` / ``…_HERE``) — so we never try to start a server
        that is obviously unconfigured."""
        if not self.command or shutil.which(self.command) is None:
            return False
        for value in self.env.values():
            if "YOUR_" in value or value.endswith("_HERE"):
                return False
        return True

    def start(self, *, timeout: float = 15.0) -> bool:
        """Spawn + handshake + ``tools/list``. Returns ``True`` on success;
        cleans up and returns ``False`` on any failure (fail-soft)."""
        with self._lock:
            if not self.launchable():
                return False
            try:
                self._proc = subprocess.Popen(  # noqa: S603 — launching a configured MCP server
                    [self.command, *self.args],
                    stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.DEVNULL,
                    env={**os.environ, **self.env},
                )
            except OSError:
                return False
            init = self._request(
                "initialize",
                {
                    "protocolVersion": _PROTOCOL_VERSION,
                    "capabilities": {},
                    "clientInfo": _CLIENT_INFO,
                },
                timeout=timeout,
            )
            if init is None:
                self.stop()
                return False
            self._notify("notifications/initialized")
            listed = self._request("tools/list", {}, timeout=timeout)
            raw_tools = as_dict(listed).get("tools") if listed is not None else None
            if isinstance(raw_tools, list):
                self.tools = [as_dict(t) for t in raw_tools]  # type: ignore[arg-type]
            return True

    def call(
        self, tool: str, arguments: dict[str, object], *, timeout: float = 60.0
    ) -> str:
        """Invoke a remote tool; return its text content (or a fail-soft error)."""
        with self._lock:
            result = self._request(
                "tools/call", {"name": tool, "arguments": arguments}, timeout=timeout
            )
            if result is None:
                return f"(error: mcp {self.name}.{tool} — no response)"
            parts: list[str] = []
            raw_content = as_dict(result).get("content")
            blocks: list[object] = (
                list(raw_content) if isinstance(raw_content, list) else []  # type: ignore[arg-type]
            )
            for block in blocks:
                blk = as_dict(block)
                if blk.get("type") == "text":
                    parts.append(str(blk.get("text", "")))
            text = "\n".join(parts) if parts else json.dumps(result)[:4000]
            if as_dict(result).get("isError"):
                return f"(mcp error) {text}"
            return text if len(text) <= 8000 else text[:8000] + "\n…(truncated)"

    def stop(self) -> None:
        """Terminate the server subprocess (idempotent, never raises)."""
        proc = self._proc
        self._proc = None
        if proc is None:
            return
        # Avoid double-locking since start() calls stop() internally on failure
        # inside the same thread lock.
        try:
            proc.terminate()
            proc.wait(timeout=3)
        except Exception:
            with contextlib.suppress(Exception):
                proc.kill()

    # --- JSON-RPC over stdio -------------------------------------------------

    def _send(self, message: dict[str, object]) -> bool:
        proc = self._proc
        if proc is None or proc.stdin is None:
            return False
        try:
            proc.stdin.write((json.dumps(message) + "\n").encode("utf-8"))
            proc.stdin.flush()
            return True
        except (OSError, ValueError):
            return False

    def _notify(self, method: str) -> None:
        self._send({"jsonrpc": "2.0", "method": method})

    def _request(
        self, method: str, params: dict[str, object], *, timeout: float
    ) -> dict[str, object] | None:
        """Send a request and return its ``result`` dict (``None`` on error/timeout).

        Reads lines until the response with the matching id arrives, skipping
        notifications and unrelated messages (fail-soft on any decode error)."""
        self._id += 1
        req_id = self._id
        if not self._send(
            {"jsonrpc": "2.0", "id": req_id, "method": method, "params": params}
        ):
            return None
        deadline = time.monotonic() + timeout
        while True:
            line = self._readline(deadline - time.monotonic())
            if line is None:
                return None
            try:
                msg = json.loads(line)
            except json.JSONDecodeError:
                continue
            msg_d = as_dict(msg)
            if msg_d.get("id") != req_id:
                continue  # a notification or another response — keep reading
            if "error" in msg_d:
                return None
            result = msg_d.get("result")
            return as_dict(result)

    def _readline(self, timeout: float) -> str | None:
        """Read one newline-delimited message from stdout within *timeout*."""
        proc = self._proc
        if proc is None or proc.stdout is None:
            return None
        fd = proc.stdout.fileno()
        while b"\n" not in self._buf:
            if timeout <= 0:
                return None
            ready, _, _ = select.select([fd], [], [], timeout)
            if not ready:
                return None
            try:
                chunk = os.read(fd, 65536)
            except OSError:
                return None
            if not chunk:
                return None  # EOF — server died
            self._buf += chunk
        line, _, self._buf = self._buf.partition(b"\n")
        return line.decode("utf-8", "replace")


# --- config loading + tool wrapping ------------------------------------------


def load_server_specs(config_path: Path) -> list[MCPServer]:
    """Parse an ``mcpServers`` JSON config into (unstarted) :class:`MCPServer`s.

    Fail-soft: a missing/malformed config yields ``[]``."""
    try:
        raw = json.loads(config_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    servers = as_dict(as_dict(raw).get("mcpServers"))
    out: list[MCPServer] = []
    for name, spec in servers.items():
        spec_d = as_dict(spec)
        raw_args = spec_d.get("args")
        arg_items: list[object] = list(raw_args) if isinstance(raw_args, list) else []  # type: ignore[arg-type]
        raw_env = as_dict(spec_d.get("env"))
        out.append(
            MCPServer(
                name=str(name),
                command=str(spec_d.get("command", "")),
                args=[str(a) for a in arg_items],
                env={k: str(v) for k, v in raw_env.items()},
            )
        )
    return out
