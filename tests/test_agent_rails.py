"""The protected-rail guard — the agent may not overwrite kinox's own rails.

Closes hard truth #1 for the agent threat model: writes to ``alignment/`` and
``next.md`` are refused fail-CLOSED, reads are allowed, and a deliberate operator
unlock (``KINOX_UNLOCK_RAILS``) stands the guard down (the documented recovery
path). Composes with the root jail via ``combine_guards``.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from products.agent.rails import (
    PROTECTED_RAILS,
    protected_rails_guard,
    rail_write_reason,
)
from products.agent.loop import GuardBlocked


def _root(tmp_path: Path) -> Path:
    (tmp_path / "alignment").mkdir()
    (tmp_path / "alignment" / "CONSTITUTION.md").write_text("rules\n")
    (tmp_path / "next.md").write_text("memory\n")
    (tmp_path / "products").mkdir()
    return tmp_path


def test_write_to_rail_is_refused(tmp_path: Path) -> None:
    guard = protected_rails_guard(_root(tmp_path))
    with pytest.raises(GuardBlocked):
        guard("write_file", '{"path": "alignment/CONSTITUTION.md"}')
    with pytest.raises(GuardBlocked):
        guard("write_file", '{"path": "next.md"}')
    # The denial names the rail as "protected" and is a refusal (checker language).
    with pytest.raises(GuardBlocked) as exc:
        guard("write_file", '{"path": "alignment/AXIOMS.md"}')
    reason = str(exc.value)
    assert "protected" in reason and "refused" in reason


def test_non_rail_write_is_allowed(tmp_path: Path) -> None:
    guard = protected_rails_guard(_root(tmp_path))
    assert guard("write_file", '{"path": "products/x.py"}') is None


def test_reading_a_rail_is_allowed(tmp_path: Path) -> None:
    # An agent must be able to READ the axioms it follows — only writes are refused.
    guard = protected_rails_guard(_root(tmp_path))
    assert guard("read_file", '{"path": "alignment/CONSTITUTION.md"}') is None
    assert guard("run_bash", '{"command": "cat alignment/AXIOMS.md"}') is None
    grep = '{"command": "grep thesis alignment/CONSTITUTION.md"}'
    assert guard("run_bash", grep) is None


def test_bash_mutation_of_a_rail_is_refused(tmp_path: Path) -> None:
    guard = protected_rails_guard(_root(tmp_path))
    with pytest.raises(GuardBlocked):
        guard("run_bash", '{"command": "echo x > alignment/AXIOMS.md"}')
    with pytest.raises(GuardBlocked):
        guard("run_bash", '{"command": "rm alignment/CONSTITUTION.md"}')
    with pytest.raises(GuardBlocked):
        guard("run_bash", '{"command": "sed -i s/a/b/ next.md"}')


def test_unlock_stands_the_guard_down(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The documented recovery path: a deliberate operator edit of the rails.
    monkeypatch.setenv("KINOX_UNLOCK_RAILS", "1")
    guard = protected_rails_guard(_root(tmp_path))
    assert guard("write_file", '{"path": "alignment/CONSTITUTION.md"}') is None
    assert guard("run_bash", '{"command": "rm alignment/AXIOMS.md"}') is None


def test_rail_write_reason_is_the_shared_ground_truth(tmp_path: Path) -> None:
    # The eval executor and the guard call this one function (thesis #1).
    root = _root(tmp_path)
    assert rail_write_reason("alignment/CONSTITUTION.md", root) is not None
    assert rail_write_reason("products/x.py", root) is None
    assert rail_write_reason("next.md", root, unlocked=True) is None
    assert "alignment" in PROTECTED_RAILS and "next.md" in PROTECTED_RAILS
