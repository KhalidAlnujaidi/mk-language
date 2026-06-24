"""Tests for daemon.hooks — the hook registry + chain engine (Brick B).

Thesis #2 (fail-direction is per-component) is the load-bearing constraint:
CLOSED hooks stop the chain on denial or failure; SOFT hooks absorb errors and
continue. Every test exercises the chain runner in isolation with stub handlers.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from daemon.hooks import HookChain, HookDecl, HookResult, load_chain
from kernel.contracts import FailDirection

# ---------------------------------------------------------------------------
# Stub handlers
# ---------------------------------------------------------------------------


async def _allow(_input: dict[str, object]) -> HookResult:
    return HookResult.allow()


async def _add_ctx(_input: dict[str, object]) -> HookResult:
    return HookResult.allow(lines=("ctx: git branch main",))


async def _deny(_input: dict[str, object]) -> HookResult:
    return HookResult.deny("not allowed")


async def _raise(_input: dict[str, object]) -> HookResult:
    raise RuntimeError("boom")


# ---------------------------------------------------------------------------
# HookDecl
# ---------------------------------------------------------------------------


def test_hook_decl_stores_fail_direction():
    decl = HookDecl(
        name="guard",
        kind="pre_inference",
        fail_direction=FailDirection.CLOSED,
        handler=_allow,
    )
    assert decl.fail_direction == FailDirection.CLOSED
    assert decl.name == "guard"
    assert decl.kind == "pre_inference"


# ---------------------------------------------------------------------------
# HookResult
# ---------------------------------------------------------------------------


def test_hook_result_allow_defaults():
    r = HookResult.allow()
    assert r.decision == "allow"
    assert r.context_lines == ()
    assert r.reason == ""


def test_hook_result_allow_with_context():
    r = HookResult.allow(lines=("hello", "world"))
    assert r.decision == "allow"
    assert r.context_lines == ("hello", "world")


def test_hook_result_deny():
    r = HookResult.deny("blocked by policy")
    assert r.decision == "deny"
    assert r.reason == "blocked by policy"


# ---------------------------------------------------------------------------
# HookChain — empty chain
# ---------------------------------------------------------------------------


def test_empty_chain_returns_allow():
    chain = HookChain(hooks=[])
    result = asyncio.run(chain.run({"prompt": "hi"}))
    assert result.decision == "allow"
    assert result.context_lines == ()


# ---------------------------------------------------------------------------
# HookChain — single hook, allow
# ---------------------------------------------------------------------------


def test_single_soft_hook_allows():
    chain = HookChain(
        hooks=[HookDecl("ctx", "pre_inference", FailDirection.SOFT, _add_ctx)]
    )
    result = asyncio.run(chain.run({"prompt": "hi"}))
    assert result.decision == "allow"
    assert "ctx: git branch main" in result.context_lines


# ---------------------------------------------------------------------------
# HookChain — single hook, deny
# ---------------------------------------------------------------------------


def test_single_closed_hook_denies_and_stops():
    chain = HookChain(
        hooks=[HookDecl("guard", "pre_inference", FailDirection.CLOSED, _deny)]
    )
    result = asyncio.run(chain.run({"prompt": "rm -rf"}))
    assert result.decision == "deny"
    assert result.reason == "not allowed"


# ---------------------------------------------------------------------------
# HookChain — multi-hook, context accumulation
# ---------------------------------------------------------------------------


def test_chain_accumulates_context_from_all_hooks():
    async def add_a(_input: dict[str, object]) -> HookResult:
        return HookResult.allow(lines=("a",))
    async def add_b(_input: dict[str, object]) -> HookResult:
        return HookResult.allow(lines=("b",))

    chain = HookChain(hooks=[
        HookDecl("a", "pre_inference", FailDirection.SOFT, add_a),
        HookDecl("b", "pre_inference", FailDirection.SOFT, add_b),
    ])
    result = asyncio.run(chain.run({}))
    assert result.decision == "allow"
    assert result.context_lines == ("a", "b")


# ---------------------------------------------------------------------------
# HookChain — CLOSED failure stops the chain
# ---------------------------------------------------------------------------


def test_closed_hook_that_raises_stops_chain():
    """A CLOSED hook that raises must halt the chain immediately."""
    called_after: list[str] = []

    async def after(_input: dict[str, object]) -> HookResult:
        called_after.append("ran")
        return HookResult.allow()

    chain = HookChain(hooks=[
        HookDecl("flaky", "pre_inference", FailDirection.CLOSED, _raise),
        HookDecl("after", "pre_inference", FailDirection.SOFT, after),
    ])
    result = asyncio.run(chain.run({}))
    assert result.decision == "deny"
    assert "flaky" in result.reason
    assert called_after == []  # second hook never ran


# ---------------------------------------------------------------------------
# HookChain — SOFT failure continues the chain
# ---------------------------------------------------------------------------


def test_soft_hook_that_raises_is_absorbed():
    """A SOFT hook that raises is skipped; the chain continues."""
    called_after: list[str] = []

    async def after(_input: dict[str, object]) -> HookResult:
        called_after.append("ran")
        return HookResult.allow(lines=("survived",))

    chain = HookChain(hooks=[
        HookDecl("flaky", "pre_inference", FailDirection.SOFT, _raise),
        HookDecl("after", "pre_inference", FailDirection.SOFT, after),
    ])
    result = asyncio.run(chain.run({}))
    assert result.decision == "allow"
    assert called_after == ["ran"]
    assert result.context_lines == ("survived",)


# ---------------------------------------------------------------------------
# HookChain — first deny wins (even if later hooks would allow)
# ---------------------------------------------------------------------------


def test_first_deny_stops_chain():
    called_after: list[str] = []

    async def after(_input: dict[str, object]) -> HookResult:
        called_after.append("ran")
        return HookResult.allow()

    chain = HookChain(hooks=[
        HookDecl("guard", "pre_inference", FailDirection.CLOSED, _deny),
        HookDecl("after", "pre_inference", FailDirection.SOFT, after),
    ])
    result = asyncio.run(chain.run({}))
    assert result.decision == "deny"
    assert called_after == []


# ---------------------------------------------------------------------------
# Per-project config loading
# ---------------------------------------------------------------------------


def test_load_chain_from_toml(tmp_path: Path):
    project = tmp_path / "myproject"
    project.mkdir()
    (project / "hooks.toml").write_text("""
[hooks]
pre_inference = ["groom", "ctx"]
""")

    registry = {
        "groom": HookDecl("groom", "pre_inference", FailDirection.SOFT, _add_ctx),
        "ctx": HookDecl("ctx", "pre_inference", FailDirection.SOFT, _add_ctx),
        "guard": HookDecl("guard", "pre_inference", FailDirection.CLOSED, _deny),
    }

    chain = load_chain(project, registry, kind="pre_inference")
    assert len(chain.hooks) == 2
    assert chain.hooks[0].name == "groom"
    assert chain.hooks[1].name == "ctx"


def test_load_chain_unknown_hook_raises(tmp_path: Path):
    project = tmp_path / "myproject"
    project.mkdir()
    (project / "hooks.toml").write_text("""
[hooks]
pre_inference = ["nonexistent"]
""")

    with pytest.raises(KeyError, match="nonexistent"):
        load_chain(project, {}, kind="pre_inference")


def test_load_chain_no_config_returns_empty_chain(tmp_path: Path):
    project = tmp_path / "myproject"
    project.mkdir()
    # No hooks.toml at all.
    chain = load_chain(project, {}, kind="pre_inference")
    assert chain.hooks == []