"""Tests for the scope-aware agent preamble compilation.

Two scopes, told only what each should know:
- **project** scope → the operating axioms alone (``alignment/AXIOMS.md``);
- **framework** scope → axioms + framework internals (``alignment/PREAMBLE.md``).

Verifies the two builders, the ``session_preamble`` switch, fail-soft on missing
files, truncation, caching, and — against the real repo — that a project scope
never leaks framework internals.
"""

from __future__ import annotations

from pathlib import Path

from products.agent.environment import (
    build_axioms,
    build_preamble,
    clear_cache,
    session_preamble,
)


def _write(root: Path, name: str, body: str) -> None:
    """Create ``<root>/alignment/<name>`` with *body*."""
    (root / "alignment").mkdir(exist_ok=True)
    (root / "alignment" / name).write_text(body, encoding="utf-8")


# --- build_axioms (project scope) --------------------------------------------


def test_axioms_reads_axioms_file(tmp_path: Path) -> None:
    _write(tmp_path, "AXIOMS.md", "Rule Zero — search and reuse.")
    clear_cache()
    assert "Rule Zero" in build_axioms(tmp_path)


def test_axioms_ignores_framework_internals(tmp_path: Path) -> None:
    """A project scope is told the axioms and nothing about the framework."""
    _write(tmp_path, "AXIOMS.md", "the axioms")
    _write(tmp_path, "PREAMBLE.md", "ARCHITECTURE MAP — secret framework internals")
    clear_cache()
    axioms = build_axioms(tmp_path)
    assert axioms == "the axioms"
    assert "framework internals" not in axioms


def test_axioms_missing_returns_empty(tmp_path: Path) -> None:
    clear_cache()
    assert build_axioms(tmp_path) == ""


# --- build_preamble (framework scope) ----------------------------------------


def test_preamble_combines_axioms_then_framework(tmp_path: Path) -> None:
    _write(tmp_path, "AXIOMS.md", "AX-BODY")
    _write(tmp_path, "PREAMBLE.md", "FW-BODY")
    clear_cache()
    p = build_preamble(tmp_path)
    assert "AX-BODY" in p and "FW-BODY" in p
    assert p.index("AX-BODY") < p.index("FW-BODY")  # axioms first


def test_preamble_with_only_axioms(tmp_path: Path) -> None:
    _write(tmp_path, "AXIOMS.md", "just axioms")
    clear_cache()
    assert build_preamble(tmp_path) == "just axioms"


def test_preamble_empty_when_no_files(tmp_path: Path) -> None:
    clear_cache()
    assert build_preamble(tmp_path) == ""


def test_preamble_truncates_long_content(tmp_path: Path) -> None:
    from products.agent import environment as env_mod

    _write(tmp_path, "AXIOMS.md", "X" * 20_000)
    clear_cache()
    p = build_preamble(tmp_path)
    assert len(p) <= env_mod._MAX_PREAMBLE + 200
    assert "truncated" in p.lower()


def test_preamble_is_cached(tmp_path: Path) -> None:
    _write(tmp_path, "AXIOMS.md", "cached body")
    clear_cache()
    first = build_preamble(tmp_path)
    (tmp_path / "alignment" / "AXIOMS.md").unlink()
    assert build_preamble(tmp_path) == first  # cached despite the deletion
    clear_cache()


# --- session_preamble (the scope switch) -------------------------------------


def test_session_switch_project_vs_framework(tmp_path: Path) -> None:
    _write(tmp_path, "AXIOMS.md", "AX")
    _write(tmp_path, "PREAMBLE.md", "FW-INTERNALS")
    clear_cache()
    project = session_preamble(tmp_path, framework=False)
    framework = session_preamble(tmp_path, framework=True)
    assert "AX" in project and "FW-INTERNALS" not in project  # project: no leak
    assert "AX" in framework and "FW-INTERNALS" in framework  # framework: both


# --- against the real repo ---------------------------------------------------


def test_real_repo_project_scope_hides_framework_internals() -> None:
    """The shipped axioms carry the rules but not the architecture map."""
    repo_root = Path(__file__).resolve().parents[1]
    clear_cache()
    project = session_preamble(repo_root, framework=False)
    framework = session_preamble(repo_root, framework=True)
    assert project and "Rule Zero" in project  # the rules reach a project
    assert "Architecture map" not in project  # framework internals do not
    assert "Architecture map" in framework  # but the framework scope sees them
