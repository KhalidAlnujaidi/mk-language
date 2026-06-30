"""Tests for products.capabilities — the skill/agent/MCP loader + registry.

Synthetic fixtures keep these hermetic; one skipif-guarded smoke test exercises
the real ECC bundle under cheatcodes/ when it happens to be present locally.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from products.capabilities import (
    AGENT,
    COMMAND,
    MCP_SERVER,
    SKILL,
    CapabilityRegistry,
    load_agents,
    load_commands,
    load_mcp,
    load_skills,
)

REPO = Path(__file__).resolve().parent.parent


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


# --- commands ---------------------------------------------------------------


def test_load_commands_parses_description_and_stem_name(tmp_path: Path) -> None:
    _write(
        tmp_path / "commands" / "code-review.md",
        "---\ndescription: Review the diff\nargument-hint: [pr]\n---\n# Code Review\n",
    )
    caps = load_commands(tmp_path / "commands")
    assert len(caps) == 1
    assert caps[0].kind == COMMAND
    assert caps[0].name == "code-review"  # from the filename stem
    assert caps[0].description == "Review the diff"
    assert caps[0].extra["argument-hint"] == "[pr]"


def test_load_commands_absent_dir_is_empty(tmp_path: Path) -> None:
    assert load_commands(tmp_path / "nope") == ()


def test_from_claude_dir_aggregates_all_kinds(tmp_path: Path) -> None:
    claude = tmp_path / ".claude"
    _write(claude / "skills" / "s1" / "SKILL.md", "---\nname: s1\ndesc: d\n---\n")
    _write(claude / "commands" / "c1.md", "---\ndescription: cmd\n---\n")
    _write(claude / "agents" / "a1.md", "---\nname: a1\ndescription: ag\n---\n")
    _write(
        claude / "mcp-servers.json",
        '{"mcpServers": {"m1": {"command": "x", "description": "srv"}}}',
    )
    reg = CapabilityRegistry.from_claude_dir(claude)
    kinds = {c.kind for c in reg.capabilities}
    assert kinds == {SKILL, COMMAND, AGENT, MCP_SERVER}
    assert len(reg) == 4


# --- skills -----------------------------------------------------------------


def test_load_skills_parses_frontmatter(tmp_path: Path) -> None:
    _write(
        tmp_path / "skills" / "redactor" / "SKILL.md",
        "---\nname: redactor\ndescription: Strip secrets.\n"
        "metadata:\n  origin: x\n---\nbody",
    )
    caps = load_skills(tmp_path / "skills")
    assert len(caps) == 1
    assert caps[0].name == "redactor"
    assert caps[0].kind == SKILL
    assert caps[0].description == "Strip secrets."


def test_load_skills_falls_back_to_dirname(tmp_path: Path) -> None:
    _write(tmp_path / "skills" / "nameless" / "SKILL.md", "no frontmatter here")
    caps = load_skills(tmp_path / "skills")
    assert caps[0].name == "nameless"  # dir name when frontmatter absent


def test_load_skills_missing_dir_is_soft(tmp_path: Path) -> None:
    assert load_skills(tmp_path / "nope") == ()  # fail-soft, no raise


# --- agents -----------------------------------------------------------------


def test_load_agents_captures_model_and_tools(tmp_path: Path) -> None:
    _write(
        tmp_path / "agents" / "rust-reviewer.md",
        "---\nname: rust-reviewer\ndescription: Reviews Rust.\n"
        'tools: ["Read", "Grep"]\nmodel: sonnet\n---\nprompt',
    )
    caps = load_agents(tmp_path / "agents")
    assert caps[0].kind == AGENT
    assert caps[0].name == "rust-reviewer"
    assert caps[0].extra["model"] == "sonnet"
    assert "Read" in caps[0].extra["tools"]


# --- mcp ---------------------------------------------------------------------


def test_load_mcp_parses_servers(tmp_path: Path) -> None:
    cfg = tmp_path / "mcp.json"
    _write(
        cfg,
        '{"mcpServers": {"github": {"command": "npx", '
        '"args": ["-y", "srv"], "description": "GitHub ops"}}}',
    )
    caps = load_mcp(cfg)
    assert len(caps) == 1
    assert caps[0].kind == MCP_SERVER
    assert caps[0].name == "github"
    assert caps[0].extra["command"] == "npx"
    assert "srv" in caps[0].extra["args"]


def test_load_mcp_malformed_json_is_soft(tmp_path: Path) -> None:
    cfg = tmp_path / "broken.json"
    _write(cfg, "{not valid json")
    assert load_mcp(cfg) == ()  # fail-soft


def test_load_mcp_missing_file_is_soft(tmp_path: Path) -> None:
    assert load_mcp(tmp_path / "absent.json") == ()


# --- registry aggregation ---------------------------------------------------


def test_registry_from_ecc_aggregates_and_queries(tmp_path: Path) -> None:
    _write(
        tmp_path / "skills" / "s1" / "SKILL.md",
        "---\nname: s1\ndescription: d1\n---\n",
    )
    _write(
        tmp_path / "agents" / "a1.md",
        "---\nname: a1\ndescription: d2\n---\n",
    )
    _write(
        tmp_path / "mcp-configs" / "mcp-servers.json",
        '{"mcpServers": {"m1": {"command": "c", "description": "d3"}}}',
    )
    reg = CapabilityRegistry.from_ecc(tmp_path)
    assert len(reg) == 3
    assert {c.kind for c in reg.capabilities} == {SKILL, AGENT, MCP_SERVER}
    assert len(reg.by_kind(SKILL)) == 1
    assert reg.get("a1") is not None
    assert reg.get("missing") is None


def test_registry_empty_ecc_is_soft(tmp_path: Path) -> None:
    reg = CapabilityRegistry.from_ecc(tmp_path / "no-ecc-here")
    assert len(reg) == 0


# --- smoke test against the real ECC bundle (only if present locally) -------

_ECC = REPO / "cheatcodes" / "ECC"


@pytest.mark.skipif(not _ECC.is_dir(), reason="ECC bundle not present")
def test_real_ecc_registers_many_capabilities() -> None:
    reg = CapabilityRegistry.from_ecc(_ECC)
    assert len(reg.by_kind(SKILL)) > 100  # 271 SKILL.md at time of writing
    assert len(reg.by_kind(AGENT)) > 30  # 67 agents
    assert len(reg.by_kind(MCP_SERVER)) >= 1
