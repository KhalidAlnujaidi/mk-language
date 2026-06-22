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


# ---------------------------------------------------------------------------
# Fix 2: expand must not match emails as @-mentions
# ---------------------------------------------------------------------------


def test_expand_email_produces_no_at_mention_note() -> None:
    """An email like user@example.com must NOT produce an @-mention note."""
    r = expand.expand("send to user@example.com please")
    assert r.notes == ()


def test_expand_real_at_path_after_whitespace_still_matches() -> None:
    """A real @path after whitespace must still be detected."""
    r = expand.expand("see @/etc/hostname for details")
    assert len(r.notes) == 1
    assert "@/etc/hostname" in r.notes[0]


def test_expand_at_path_at_start_of_string_matches() -> None:
    """An @path at start of string (no leading whitespace) must still match."""
    r = expand.expand("@/etc/hostname is the file")
    assert len(r.notes) == 1
    assert "@/etc/hostname" in r.notes[0]


# ---------------------------------------------------------------------------
# Fix 5: redact coverage for openai_key, aws_key, generic_hex_token + cumulative
# ---------------------------------------------------------------------------

import pytest  # noqa: E402 — after stdlib imports; acceptable in test module


@pytest.mark.parametrize(
    "text, expected_kind",
    [
        (
            "token is sk-AAAABBBBCCCCDDDDEEEE123 done",
            "openai_key",
        ),
        (
            "key AKIAIOSFODNN7EXAMPLE done",
            "aws_key",
        ),
        (
            "hex 0123456789abcdef0123456789abcdef done",
            "generic_hex_token",
        ),
    ],
)
def test_redact_parametrized_patterns(text: str, expected_kind: str) -> None:
    """Each non-anthropic secret pattern is redacted and its kind reported."""
    r = redact.redact(text)
    assert expected_kind in r.found
    assert f"«REDACTED:{expected_kind}»" in r.text


def test_redact_two_secrets_cumulative() -> None:
    """A string with two different secrets must redact both and report both kinds."""
    text = "key AKIAIOSFODNN7EXAMPLE and hex 0123456789abcdef0123456789abcdef end"
    r = redact.redact(text)
    assert "aws_key" in r.found
    assert "generic_hex_token" in r.found
    assert "AKIAIOSFODNN7EXAMPLE" not in r.text
    assert "0123456789abcdef0123456789abcdef" not in r.text
