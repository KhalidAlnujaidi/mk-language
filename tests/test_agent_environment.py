"""Tests for the kinox environment preamble compilation.

Verifies that :func:`build_preamble` reads the single canonical preamble source
(``alignment/PREAMBLE.md``), returns it verbatim, truncates when too long,
handles a missing file (fail-soft), reads *only* that file, and caches per root.
"""

from __future__ import annotations

from pathlib import Path

from products.agent.environment import build_preamble, clear_cache


def _write_preamble(root: Path, body: str) -> None:
    """Create ``<root>/alignment/PREAMBLE.md`` with *body*."""
    (root / "alignment").mkdir(exist_ok=True)
    (root / "alignment" / "PREAMBLE.md").write_text(body, encoding="utf-8")


def test_build_preamble_reads_canonical_file(tmp_path: Path) -> None:
    """The preamble is the content of ``alignment/PREAMBLE.md``."""
    _write_preamble(tmp_path, "# CONSTITUTION\n\nRule Zero — search and reuse.")
    clear_cache()
    preamble = build_preamble(tmp_path)
    assert "CONSTITUTION" in preamble
    assert "Rule Zero" in preamble


def test_build_preamble_reads_only_canonical_source(tmp_path: Path) -> None:
    """Only PREAMBLE.md is read — the old multi-file sources are ignored."""
    _write_preamble(tmp_path, "canonical preamble body")
    # These were inlined under the old design; the new one must NOT read them.
    (tmp_path / "BRAIN.md").write_text("brain body")
    (tmp_path / "vision.md").write_text("vision body")
    (tmp_path / "README.md").write_text("readme body")
    clear_cache()
    preamble = build_preamble(tmp_path)
    assert preamble == "canonical preamble body"
    for stray in ("brain body", "vision body", "readme body"):
        assert stray not in preamble


def test_build_preamble_missing_file_returns_empty(tmp_path: Path) -> None:
    """A missing PREAMBLE.md returns '' (fail-soft) even if other files exist."""
    (tmp_path / "BRAIN.md").write_text("brain body")  # not the canonical source
    clear_cache()
    assert build_preamble(tmp_path) == ""


def test_build_preamble_empty_when_no_files(tmp_path: Path) -> None:
    """Returns empty string when no preamble file exists."""
    clear_cache()
    assert build_preamble(tmp_path) == ""


def test_build_preamble_truncates_long_content(tmp_path: Path) -> None:
    """An over-long preamble is truncated with a marker."""
    from products.agent import environment as env_mod

    _write_preamble(tmp_path, "X" * 20_000)
    clear_cache()
    preamble = build_preamble(tmp_path)
    assert len(preamble) <= env_mod._MAX_PREAMBLE + 200  # body + truncation note
    assert "truncated" in preamble.lower()


def test_build_preamble_is_cached(tmp_path: Path) -> None:
    """Repeated calls with the same root return the cached result."""
    _write_preamble(tmp_path, "cached body")
    clear_cache()
    first = build_preamble(tmp_path)
    # Delete the file — cached result should still be returned.
    (tmp_path / "alignment" / "PREAMBLE.md").unlink()
    second = build_preamble(tmp_path)
    assert first == second
    assert "cached body" in first
    clear_cache()


def test_build_preamble_uses_real_repo() -> None:
    """Building against the actual kinox repo root yields a meaningful preamble."""
    repo_root = Path(__file__).resolve().parents[1]
    clear_cache()
    preamble = build_preamble(repo_root)
    # The real repo ships alignment/PREAMBLE.md — a non-empty kinox summary.
    assert preamble
    assert "kinox" in preamble.lower()
