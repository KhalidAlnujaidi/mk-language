"""Tool registry + built-in tools: dispatch is fail-soft, the filesystem is
sandboxed (guard fails CLOSED on escape), and the skill bridge reads the corpus.
"""

from __future__ import annotations

from pathlib import Path

from products.agent.tools import (
    Tool,
    ToolRegistry,
    default_registry,
    filesystem_tools,
    skill_tools,
)
from products.capabilities.registry import CapabilityRegistry, load_skills


def _echo_tool() -> Tool:
    return Tool(
        name="echo",
        description="echo back",
        parameters={"type": "object", "properties": {"x": {"type": "string"}}},
        handler=lambda a: f"got:{a.get('x')}",
    )


def test_registry_schema_and_dispatch() -> None:
    reg = ToolRegistry()
    reg.register(_echo_tool())
    schema = reg.schemas()
    assert schema[0]["function"]["name"] == "echo"  # type: ignore[index]
    assert reg.dispatch("echo", '{"x": "hi"}') == "got:hi"
    assert reg.dispatch("echo", {"x": "hi"}) == "got:hi"  # dict args too


def test_dispatch_fails_soft() -> None:
    reg = ToolRegistry()
    reg.register(_echo_tool())
    assert "unknown tool" in reg.dispatch("nope", "{}")
    assert "bad JSON" in reg.dispatch("echo", "{not json")

    def boom(_a: dict[str, object]) -> str:
        raise RuntimeError("kaboom")

    reg.register(Tool("boom", "", {"type": "object", "properties": {}}, boom))
    out = reg.dispatch("boom", "{}")
    assert "tool error" in out and "kaboom" in out


def test_filesystem_tools_sandboxed(tmp_path: Path) -> None:
    (tmp_path / "a.txt").write_text("hello", encoding="utf-8")
    (tmp_path / "sub").mkdir()
    tools = {t.name: t for t in filesystem_tools(tmp_path)}

    assert tools["read_file"].handler({"path": "a.txt"}) == "hello"
    listing = tools["list_dir"].handler({"path": "."})
    assert "a.txt" in listing and "sub/" in listing

    # Path traversal escaping the root fails CLOSED.
    assert "escapes" in tools["read_file"].handler({"path": "../../etc/passwd"})
    assert "not a file" in tools["read_file"].handler({"path": "sub"})


def test_skill_bridge_reads_corpus(tmp_path: Path) -> None:
    skills_dir = tmp_path / "skills"
    (skills_dir / "safety-guard").mkdir(parents=True)
    (skills_dir / "safety-guard" / "SKILL.md").write_text(
        "---\nname: safety-guard\n"
        "description: Prevent destructive operations during autonomous runs.\n"
        "---\n\n# Safety Guard\nDo not rm -rf.\n",
        encoding="utf-8",
    )
    registry = CapabilityRegistry(load_skills(skills_dir))
    tools = {t.name: t for t in skill_tools(registry)}

    found = tools["find_skill"].handler({"query": "destructive"})
    assert "safety-guard" in found

    miss = tools["find_skill"].handler({"query": "nonexistent-xyz"})
    assert "no skill matches" in miss

    loaded = tools["load_skill"].handler({"name": "safety-guard"})
    assert "Do not rm -rf" in loaded
    assert "no skill named" in tools["load_skill"].handler({"name": "ghost"})


def test_default_registry_gates_bash(tmp_path: Path) -> None:
    # Bash is OFF by default (fail-CLOSED); only present when explicitly allowed.
    assert "run_bash" not in default_registry(tmp_path).tools
    assert "run_bash" in default_registry(tmp_path, allow_bash=True).tools
