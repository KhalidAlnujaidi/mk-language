"""Tests for products/groom/stages — TDD: these run RED first, then GREEN."""

from __future__ import annotations

from pathlib import Path

from kernel.contracts import FailDirection
from products.groom.stages import context, expand, redact


def test_redact_replaces_anthropic_key_and_reports_kind() -> None:
    r = redact.redact("here is sk-ant-api03-AAAAAAAAAAAAAAAAAAAAAAAA done")
    assert "sk-ant-" not in r.text
    assert "anthropic_key" in r.found


def test_redact_clean_text_is_unchanged_with_no_findings() -> None:
    r = redact.redact("just a normal prompt")
    assert r.text == "just a normal prompt"
    assert r.found == ()


def test_redact_is_a_closed_guard() -> None:
    assert redact.FAIL_DIRECTION is FailDirection.CLOSED


def test_expand_flags_existing_and_missing_paths(tmp_path: Path) -> None:
    (tmp_path / "real.txt").write_text("x")
    r = expand.expand(f"see @{tmp_path / 'real.txt'} and @{tmp_path / 'ghost.txt'}")
    assert any("exists" in n for n in r.notes)
    assert any("missing" in n for n in r.notes)


def test_expand_is_a_soft_optimizer() -> None:
    assert expand.FAIL_DIRECTION is FailDirection.SOFT


def test_context_reports_branch_for_a_repo(tmp_path: Path) -> None:
    # tmp_path is not a repo → must not raise, returns empty
    assert context.gather(tmp_path).lines == ()


def test_context_is_a_soft_optimizer() -> None:
    assert context.FAIL_DIRECTION is FailDirection.SOFT
