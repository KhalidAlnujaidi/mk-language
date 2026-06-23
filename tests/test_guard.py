"""Tests for the dev-role guard (adapters/guard.py).

`decide` is pure (payload + repo_root → allow/deny); `main` adds the env gate +
stdin/JSON. Both tested without a real Claude session.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from adapters import guard


def _repo(tmp_path: Path) -> Path:
    (tmp_path / "kernel").mkdir()
    (tmp_path / "projects" / "foo").mkdir(parents=True)
    return tmp_path


def test_non_edit_tool_is_allowed(tmp_path: Path) -> None:
    payload: dict[str, object] = {
        "tool_name": "Bash",
        "tool_input": {"command": "rm -rf /"},
    }
    assert guard.decide(payload, repo_root=_repo(tmp_path))[0] == "allow"


def test_edit_to_framework_code_is_denied(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    payload: dict[str, object] = {
        "tool_name": "Edit",
        "tool_input": {"file_path": str(repo / "kernel" / "contracts.py")},
    }
    decision, reason = guard.decide(payload, repo_root=repo)
    assert decision == "deny"
    assert "framework code" in reason


def test_edit_inside_a_project_is_allowed(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    payload: dict[str, object] = {
        "tool_name": "Write",
        "tool_input": {"file_path": str(repo / "projects" / "foo" / "app.py")},
    }
    assert guard.decide(payload, repo_root=repo)[0] == "allow"


def test_edit_repo_root_config_is_denied(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    payload: dict[str, object] = {
        "tool_name": "Write",
        "tool_input": {"file_path": str(repo / "pyproject.toml")},
    }
    assert guard.decide(payload, repo_root=repo)[0] == "deny"


def test_edit_outside_the_repo_is_allowed(tmp_path: Path) -> None:
    # The guard protects framework code, not the whole filesystem.
    repo = _repo(tmp_path)
    payload: dict[str, object] = {
        "tool_name": "Edit",
        "tool_input": {"file_path": "/tmp/scratch.py"},
    }
    assert guard.decide(payload, repo_root=repo)[0] == "allow"


def test_main_is_noop_when_not_developer(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.delenv("KINOX_ROLE", raising=False)
    rc = guard.main('{"tool_name":"Edit","tool_input":{"file_path":"/x/kernel/a.py"}}')
    assert rc == 0
    assert capsys.readouterr().out == ""  # admin/unscoped → never interferes


def test_main_denies_framework_edit_for_developer(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("KINOX_ROLE", "developer")
    # adapters/guard.py → repo root is its parent's parent; kernel/ is framework.
    repo_root = Path(guard.__file__).resolve().parents[1]
    target = repo_root / "kernel" / "contracts.py"
    payload = {"tool_name": "Edit", "tool_input": {"file_path": str(target)}}
    rc = guard.main(json.dumps(payload))
    assert rc == 0
    out = capsys.readouterr().out
    assert '"permissionDecision": "deny"' in out


def test_main_fails_open_on_garbage(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("KINOX_ROLE", "developer")
    assert guard.main("not json at all") == 0
    assert capsys.readouterr().out == ""  # never block on unparseable input
