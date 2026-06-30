"""Tests for daemon.mcp — the stdio MCP client.

A tiny fake MCP server (a Python script speaking JSON-RPC 2.0 over stdio) gives a
hermetic end-to-end test of the real handshake + tools/list + tools/call, with no
network and no external server binaries.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from daemon.mcp import MCPServer, load_server_specs

# A minimal MCP server: initialize → tools/list (one echo tool) → tools/call.
_FAKE_SERVER = r'''
import sys, json

def send(obj):
    sys.stdout.write(json.dumps(obj) + "\n")
    sys.stdout.flush()

for line in sys.stdin:
    line = line.strip()
    if not line:
        continue
    msg = json.loads(line)
    mid = msg.get("id")
    method = msg.get("method")
    if method == "initialize":
        send({"jsonrpc": "2.0", "id": mid, "result": {
            "protocolVersion": "2024-11-05", "capabilities": {},
            "serverInfo": {"name": "fake", "version": "1"}}})
    elif method == "notifications/initialized":
        pass
    elif method == "tools/list":
        send({"jsonrpc": "2.0", "id": mid, "result": {"tools": [
            {"name": "echo", "description": "echo text back",
             "inputSchema": {"type": "object",
                             "properties": {"text": {"type": "string"}},
                             "required": ["text"]}}]}})
    elif method == "tools/call":
        args = (msg.get("params") or {}).get("arguments") or {}
        out = "echo:" + str(args.get("text", ""))
        send({"jsonrpc": "2.0", "id": mid,
              "result": {"content": [{"type": "text", "text": out}]}})
    elif mid is not None:
        send({"jsonrpc": "2.0", "id": mid,
              "error": {"code": -32601, "message": "method not found"}})
'''


def _fake_server(tmp_path: Path) -> Path:
    script = tmp_path / "fake_server.py"
    script.write_text(_FAKE_SERVER, encoding="utf-8")
    return script


def test_start_lists_and_calls(tmp_path: Path) -> None:
    srv = MCPServer(
        name="fake", command=sys.executable, args=[str(_fake_server(tmp_path))]
    )
    assert srv.launchable()
    try:
        assert srv.start(timeout=10.0)
        assert any(t.get("name") == "echo" for t in srv.tools)
        assert srv.call("echo", {"text": "hi"}, timeout=10.0) == "echo:hi"
    finally:
        srv.stop()


def test_launchable_filters_placeholder_env() -> None:
    srv = MCPServer("x", command=sys.executable, env={"TOKEN": "YOUR_TOKEN_HERE"})
    assert not srv.launchable()


def test_launchable_filters_missing_command() -> None:
    assert not MCPServer("x", command="definitely-not-a-real-binary-xyzzy").launchable()


def test_call_on_unstarted_server_is_soft() -> None:
    out = MCPServer("x", command=sys.executable).call("echo", {}, timeout=1.0)
    assert out.startswith("(error")


def test_load_server_specs(tmp_path: Path) -> None:
    cfg = tmp_path / "mcp.json"
    cfg.write_text(
        json.dumps(
            {"mcpServers": {"a": {"command": "echo", "args": ["x"], "env": {"K": "V"}}}}
        ),
        encoding="utf-8",
    )
    specs = load_server_specs(cfg)
    assert len(specs) == 1
    assert specs[0].name == "a" and specs[0].command == "echo"
    assert specs[0].args == ["x"] and specs[0].env == {"K": "V"}


def test_load_server_specs_absent_is_empty(tmp_path: Path) -> None:
    assert load_server_specs(tmp_path / "nope.json") == []


def test_mcp_tools_wraps_remote_end_to_end(tmp_path: Path) -> None:
    from products.agent.tools import _MCP_CACHE, mcp_tools

    cfg = tmp_path / "mcp.json"
    cfg.write_text(
        json.dumps(
            {"mcpServers": {"fake": {"command": sys.executable,
                                     "args": [str(_fake_server(tmp_path))]}}}
        ),
        encoding="utf-8",
    )
    _MCP_CACHE.clear()
    try:
        tools = mcp_tools(cfg)
        names = [t.name for t in tools]
        assert "mcp__fake__echo" in names
        echo = next(t for t in tools if t.name == "mcp__fake__echo")
        assert echo.handler({"text": "yo"}) == "echo:yo"
    finally:
        for srv in _MCP_CACHE.get(str(cfg), []):
            srv.stop()  # type: ignore[attr-defined]
        _MCP_CACHE.clear()
