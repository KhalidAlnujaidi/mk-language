"""Tests for evals.schema — EvalTask, EvalResult, and JSON loading (TASK-5-1).

TDD for the golden eval set schema. The schema defines behavioral assertions
for kinox eval tasks: "under these conditions, did the system do the right
thing?" — not exact-output matching.

Tasks are stored as JSON files in evals/tasks/ (stdlib json, no pyyaml dep).
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Helper: write a JSON snippet to a temp file, return the path
# ---------------------------------------------------------------------------


def _json_file(data: dict[str, object] | str) -> Path:
    """Write *data* to a temporary .json file and return its path.

    If *data* is a str, write it raw (for invalid-JSON tests).
    """
    fd, path = tempfile.mkstemp(suffix=".json")
    with os.fdopen(fd, "w") as fh:
        if isinstance(data, str):
            fh.write(data)
        else:
            json.dump(data, fh)
    return Path(path)


# ---------------------------------------------------------------------------
# 1. Schema classes exist and are well-formed
# ---------------------------------------------------------------------------


def test_eval_task_dataclass_exists() -> None:
    """EvalTask is a dataclass with the required fields."""
    from evals.schema import EvalTask

    task = EvalTask(
        id="test-1",
        description="a test task",
        prompt="hello",
        assertions=[],
    )
    assert task.id == "test-1"
    assert task.description == "a test task"
    assert task.prompt == "hello"
    assert task.assertions == []
    assert task.tags == []  # default
    assert task.setup == {}  # default


def test_eval_task_fields_are_required() -> None:
    """EvalTask id, description, prompt, and assertions are required."""
    from evals.schema import EvalTask

    with pytest.raises(TypeError):
        EvalTask()  # type: ignore[call-arg]


def test_assertion_dataclass_exists() -> None:
    """Assertion is a dataclass with kind, target, expected."""
    from evals.schema import Assertion

    a = Assertion(kind="contains", target="response_text", expected="hello")
    assert a.kind == "contains"
    assert a.target == "response_text"
    assert a.expected == "hello"


def test_assertion_kind_must_be_valid() -> None:
    """Assertion rejects unknown assertion kinds."""
    from evals.schema import VALID_ASSERTION_KINDS, Assertion

    # Known kinds pass
    for kind in VALID_ASSERTION_KINDS:
        a = Assertion(kind=kind, target="x", expected="y")
        assert a.kind == kind

    # Unknown kind raises
    with pytest.raises(ValueError, match="Unknown assertion kind"):
        Assertion(kind="fantasy", target="x", expected="y")


def test_eval_result_dataclass_exists() -> None:
    """EvalResult captures task result with per-assertion pass/fail."""
    from evals.schema import AssertionResult, EvalResult

    result = EvalResult(
        task_id="test-1",
        passed=True,
        assertion_results=[
            AssertionResult(kind="contains", target="x", passed=True,
                            expected="y", actual="y"),
        ],
        duration_ms=42.0,
    )
    assert result.task_id == "test-1"
    assert result.passed is True
    assert len(result.assertion_results) == 1
    assert result.duration_ms == 42.0
    assert result.trace == []  # default


def test_eval_result_failed_when_any_assertion_fails() -> None:
    """A single failing assertion makes the whole task fail."""
    from evals.schema import AssertionResult, EvalResult

    result = EvalResult(
        task_id="test-1",
        passed=True,
        assertion_results=[
            AssertionResult(kind="contains", target="a", passed=True,
                            expected="x", actual="x"),
            AssertionResult(kind="contains", target="b", passed=False,
                            expected="y", actual="z"),
        ],
        duration_ms=10.0,
    )
    assert result.assertion_results[0].passed is True
    assert result.assertion_results[1].passed is False


# ---------------------------------------------------------------------------
# 2. JSON loading — valid tasks
# ---------------------------------------------------------------------------


def test_load_task_from_json_minimal() -> None:
    """A minimal valid JSON task loads correctly."""
    from evals.schema import load_task

    path = _json_file({
        "id": "minimal-task",
        "description": "a minimal eval task",
        "prompt": "say hello",
        "assertions": [
            {"kind": "contains", "target": "response_text", "expected": "hello"},
        ],
    })
    task = load_task(path)
    assert task.id == "minimal-task"
    assert task.description == "a minimal eval task"
    assert task.prompt == "say hello"
    assert len(task.assertions) == 1
    assert task.assertions[0].kind == "contains"
    assert task.tags == []
    assert task.setup == {}


def test_load_task_with_tags_and_setup() -> None:
    """A JSON task with tags and setup loads correctly."""
    from evals.schema import load_task

    path = _json_file({
        "id": "full-task",
        "description": "task with all fields",
        "prompt": "do something",
        "tags": ["groom", "redact"],
        "setup": {
            "src/main.py": "print('hello')",
            "config.toml": "[app]\nname = 'kinox'",
        },
        "assertions": [
            {"kind": "redacted", "target": "annotation_lines", "expected": "api key"},
            {"kind": "routed", "target": "tier_where", "expected": "local"},
        ],
    })
    task = load_task(path)
    assert task.tags == ["groom", "redact"]
    assert task.setup == {
        "src/main.py": "print('hello')",
        "config.toml": "[app]\nname = 'kinox'",
    }
    assert len(task.assertions) == 2
    assert task.assertions[0].kind == "redacted"
    assert task.assertions[1].kind == "routed"


def test_load_task_with_multiple_assertion_kinds() -> None:
    """All valid assertion kinds load correctly from JSON."""
    from evals.schema import VALID_ASSERTION_KINDS, load_task

    assertions = [
        {"kind": kind, "target": "x", "expected": "y"}
        for kind in VALID_ASSERTION_KINDS
    ]
    path = _json_file({
        "id": "all-kinds",
        "description": "test all assertion kinds",
        "prompt": "test",
        "assertions": assertions,
    })
    task = load_task(path)
    assert len(task.assertions) == len(VALID_ASSERTION_KINDS)


# ---------------------------------------------------------------------------
# 3. JSON validation — error cases
# ---------------------------------------------------------------------------


def test_load_task_rejects_unknown_fields() -> None:
    """A JSON task with unknown top-level fields raises ValueError."""
    from evals.schema import load_task

    path = _json_file({
        "id": "bad-task",
        "description": "extra field",
        "prompt": "hello",
        "assertions": [],
        "banana": "should not be here",
    })
    with pytest.raises(ValueError, match="Unknown field"):
        load_task(path)


def test_load_task_rejects_unknown_assertion_kind() -> None:
    """A JSON assertion with an unknown kind raises ValueError."""
    from evals.schema import load_task

    path = _json_file({
        "id": "bad-assertion",
        "description": "bad kind",
        "prompt": "hello",
        "assertions": [
            {"kind": "telepathy", "target": "mind", "expected": "thought"},
        ],
    })
    with pytest.raises(ValueError, match="Unknown assertion kind"):
        load_task(path)


def test_load_task_rejects_missing_id() -> None:
    """A JSON task without an id raises ValueError."""
    from evals.schema import load_task

    path = _json_file({
        "description": "no id",
        "prompt": "hello",
        "assertions": [],
    })
    with pytest.raises(ValueError, match="'id'"):
        load_task(path)


def test_load_task_rejects_missing_prompt() -> None:
    """A JSON task without a prompt raises ValueError."""
    from evals.schema import load_task

    path = _json_file({
        "id": "no-prompt",
        "description": "no prompt",
        "assertions": [],
    })
    with pytest.raises(ValueError, match="'prompt'"):
        load_task(path)


def test_load_task_rejects_missing_assertions() -> None:
    """A JSON task without assertions raises ValueError."""
    from evals.schema import load_task

    path = _json_file({
        "id": "no-assertions",
        "description": "no assertions",
        "prompt": "hello",
    })
    with pytest.raises(ValueError, match="'assertions'"):
        load_task(path)


def test_load_task_rejects_empty_assertions() -> None:
    """A JSON task with an empty assertions list raises ValueError."""
    from evals.schema import load_task

    path = _json_file({
        "id": "empty-assertions",
        "description": "empty",
        "prompt": "hello",
        "assertions": [],
    })
    with pytest.raises(ValueError, match="at least one assertion"):
        load_task(path)


def test_load_task_rejects_non_list_assertions() -> None:
    """A JSON task where assertions is not a list raises ValueError."""
    from evals.schema import load_task

    path = _json_file({
        "id": "bad-assertions",
        "description": "not a list",
        "prompt": "hello",
        "assertions": "not a list",
    })
    with pytest.raises(ValueError, match="must be a list"):
        load_task(path)


def test_load_nonexistent_file_raises() -> None:
    """Loading a file that doesn't exist raises FileNotFoundError."""
    from evals.schema import load_task

    with pytest.raises(FileNotFoundError):
        load_task(Path("/nonexistent/task.json"))


def test_load_invalid_json_raises() -> None:
    """Loading malformed JSON raises ValueError."""
    from evals.schema import load_task

    path = _json_file("this is not json {")
    with pytest.raises(ValueError, match="Invalid JSON"):
        load_task(path)


# ---------------------------------------------------------------------------
# 4. Bulk loading
# ---------------------------------------------------------------------------


def test_load_all_tasks_loads_directory() -> None:
    """load_all_tasks reads every .json in a directory, sorted by id."""
    from evals.schema import load_all_tasks

    with tempfile.TemporaryDirectory() as td:
        d = Path(td)
        (d / "b-task.json").write_text(json.dumps({
            "id": "b-task", "description": "second", "prompt": "b",
            "assertions": [
                {"kind": "contains", "target": "response_text", "expected": "b"}
            ],
        }))
        (d / "a-task.json").write_text(json.dumps({
            "id": "a-task", "description": "first", "prompt": "a",
            "assertions": [
                {"kind": "contains", "target": "response_text", "expected": "a"}
            ],
        }))
        (d / "not-a-task.txt").write_text("ignored")
        tasks = load_all_tasks(d)
        assert len(tasks) == 2
        assert tasks[0].id == "a-task"  # sorted by id
        assert tasks[1].id == "b-task"


def test_load_all_tasks_empty_directory() -> None:
    """Loading from an empty directory returns an empty list."""
    from evals.schema import load_all_tasks

    with tempfile.TemporaryDirectory() as td:
        tasks = load_all_tasks(Path(td))
        assert tasks == []


def test_load_all_tasks_skips_invalid_files() -> None:
    """A directory with one valid and one invalid JSON returns only the valid one."""
    from evals.schema import load_all_tasks

    with tempfile.TemporaryDirectory() as td:
        d = Path(td)
        (d / "valid.json").write_text(json.dumps({
            "id": "valid", "description": "ok", "prompt": "hi",
            "assertions": [
                {"kind": "contains", "target": "response_text", "expected": "hi"}
            ],
        }))
        (d / "invalid.json").write_text(json.dumps({
            "id": "bad", "description": "missing prompt",
            "assertions": [],
        }))
        tasks = load_all_tasks(d)
        assert len(tasks) == 1
        assert tasks[0].id == "valid"


# ---------------------------------------------------------------------------
# 5. Schema export surface
# ---------------------------------------------------------------------------


def test_valid_assertion_kinds_is_a_frozenset() -> None:
    """VALID_ASSERTION_KINDS is a frozenset of known assertion kinds."""
    from evals.schema import VALID_ASSERTION_KINDS

    assert isinstance(VALID_ASSERTION_KINDS, frozenset)
    assert "contains" in VALID_ASSERTION_KINDS
    assert "redacted" in VALID_ASSERTION_KINDS
    assert "routed" in VALID_ASSERTION_KINDS
    assert "refused" in VALID_ASSERTION_KINDS
    assert "not_contains" in VALID_ASSERTION_KINDS
    assert "schema" in VALID_ASSERTION_KINDS
