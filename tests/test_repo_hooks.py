"""The repo-local .claude/settings.json vendors the framework pipeline.

Piece 2 of the governed-TUI spec: a Claude Code session launched inside the repo
runs kinox's OWN groom + dev-guard hooks, not the user's global ones. These tests
pin that the settings file is valid JSON and wires both adapters.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parent.parent
SETTINGS = REPO / ".claude" / "settings.json"


def _load() -> Any:
    # json.loads returns Any; the settings shape is asserted structurally below.
    return json.loads(SETTINGS.read_text(encoding="utf-8"))


def test_settings_file_exists_and_is_valid_json() -> None:
    assert SETTINGS.exists(), "repo-local .claude/settings.json is missing"
    _load()  # raises on invalid JSON


def test_groom_hook_registered_on_user_prompt_submit() -> None:
    data = _load()
    commands = [
        hook["command"]
        for group in data["hooks"]["UserPromptSubmit"]
        for hook in group["hooks"]
    ]
    assert any("adapters/claude_code.py" in cmd for cmd in commands)


def test_dev_guard_registered_on_pre_tool_use_edit_tools() -> None:
    data = _load()
    groups = data["hooks"]["PreToolUse"]
    # The guard must target the file-editing tools it knows how to gate.
    guard = next(
        g
        for g in groups
        if any("adapters/guard.py" in h["command"] for h in g["hooks"])
    )
    for tool in ("Write", "Edit", "MultiEdit", "NotebookEdit"):
        assert tool in guard["matcher"]


def test_hook_commands_are_repo_relative() -> None:
    """Commands resolve under $CLAUDE_PROJECT_DIR so the file is portable."""
    data = _load()
    all_commands = [
        hook["command"]
        for event in data["hooks"].values()
        for group in event
        for hook in group["hooks"]
    ]
    assert all_commands
    assert all("$CLAUDE_PROJECT_DIR" in cmd for cmd in all_commands)
