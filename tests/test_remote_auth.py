"""Tests for daemon/remote_auth.py — the bearer-token gate (P1).

Pure policy: no FastAPI, no network. The gate is deterministic ground truth
(thesis #1) and fail-CLOSED (thesis #2), so every branch is asserted offline.
"""

from __future__ import annotations

from pathlib import Path

from daemon.remote_auth import (
    authorize,
    bearer_from_headers,
    generate_token,
    load_tokens,
    requires_token,
    token_matches_any,
)


def test_generate_token_is_unique_and_substantial() -> None:
    a, b = generate_token(), generate_token()
    assert a != b
    assert len(a) >= 32


def test_load_tokens_reads_token_files(tmp_path: Path) -> None:
    (tmp_path / "phone.token").write_text("alpha\n", encoding="utf-8")
    (tmp_path / "laptop.token").write_text("beta", encoding="utf-8")
    (tmp_path / "notes.txt").write_text("ignored", encoding="utf-8")  # wrong suffix
    (tmp_path / "empty.token").write_text("  \n", encoding="utf-8")  # blank → skipped
    assert load_tokens(tmp_path) == frozenset({"alpha", "beta"})


def test_load_tokens_absent_dir_is_empty(tmp_path: Path) -> None:
    assert load_tokens(tmp_path / "nope") == frozenset()
    assert load_tokens(None) == frozenset()


def test_token_matches_any() -> None:
    valid = frozenset({"alpha", "beta"})
    assert token_matches_any("beta", valid) is True
    assert token_matches_any("gamma", valid) is False
    assert token_matches_any("", valid) is False
    assert token_matches_any("alpha", frozenset()) is False


def test_bearer_parsing() -> None:
    assert bearer_from_headers({"Authorization": "Bearer xyz"}) == "xyz"
    assert bearer_from_headers({"authorization": "bearer xyz"}) == "xyz"  # case-insens
    assert bearer_from_headers({"Authorization": "Basic xyz"}) is None
    assert bearer_from_headers({"Authorization": "Bearer"}) is None  # no token
    assert bearer_from_headers({}) is None


def test_authorize_local_is_trusted_without_token() -> None:
    # Local (Unix socket / loopback) needs no token even when none are configured.
    assert authorize({}, frozenset(), is_local=True) is None


def test_authorize_network_denies_when_unconfigured() -> None:
    reason = authorize({"Authorization": "Bearer x"}, frozenset(), is_local=False)
    assert reason is not None and "not configured" in reason


def test_authorize_network_requires_valid_token() -> None:
    valid = frozenset({"good"})
    assert authorize({}, valid, is_local=False) == "missing bearer token"
    assert (
        authorize({"Authorization": "Bearer bad"}, valid, is_local=False)
        == "invalid token"
    )
    assert authorize({"Authorization": "Bearer good"}, valid, is_local=False) is None


def test_authorize_never_echoes_the_presented_token() -> None:
    headers = {"Authorization": "Bearer s3cr3t"}
    reason = authorize(headers, frozenset({"x"}), is_local=False)
    assert reason is not None and "s3cr3t" not in reason


def test_requires_token_only_for_remote_hosts() -> None:
    for local in ("", "127.0.0.1", "::1", "localhost"):
        assert requires_token(local) is False
    assert requires_token(None) is False  # Unix-socket path → no host
    for remote in ("0.0.0.0", "100.64.164.41", "192.168.1.10"):  # noqa: S104
        assert requires_token(remote) is True
