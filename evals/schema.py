"""Eval task schema — behavioral assertions for the golden eval set (TASK-5-1).

Defines ``EvalTask`` (a single eval case), ``EvalResult`` (the outcome of
running one), and the JSON loader.  Tasks are stored as ``*.json`` files in
``evals/tasks/`` — stdlib ``json``, zero dependencies.

A kinox eval task is NOT exact-output matching.  It is a **behavioral
assertion**: "under these conditions, did the system do the right thing?"
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import cast

# ---------------------------------------------------------------------------
# Known assertion kinds
# ---------------------------------------------------------------------------

VALID_ASSERTION_KINDS: frozenset[str] = frozenset({
    "contains",      # target text contains expected substring
    "not_contains",  # target text does NOT contain expected substring
    "redacted",      # target text had a secret removed (expected = secret type)
    "routed",        # tier_where / tier_model_name matches expected
    "refused",       # destructive action was denied (expected = action verb)
    "schema",        # target output matches expected JSON schema shape
})

# ---------------------------------------------------------------------------
# Schema dataclasses
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Assertion:
    """One behavioral check within an eval task.

    *kind* must be a member of ``VALID_ASSERTION_KINDS``.  *target* names what
    to inspect (e.g. ``"response_text"``, ``"tier_where"``,
    ``"annotation_lines"``).  *expected* is the value or pattern to match.
    """

    kind: str
    target: str
    expected: str

    def __post_init__(self) -> None:
        if self.kind not in VALID_ASSERTION_KINDS:
            raise ValueError(
                f"Unknown assertion kind {self.kind!r}. "
                f"Valid: {sorted(VALID_ASSERTION_KINDS)}"
            )


@dataclass(frozen=True)
class AssertionResult:
    """The outcome of a single assertion after running the task."""

    kind: str
    target: str
    passed: bool
    expected: str
    actual: str


def _empty_str_list() -> list[str]:
    """Typed empty-list factory — `default_factory=list` erases the element type."""
    return []


def _empty_str_dict() -> dict[str, str]:
    """Typed empty-dict factory — `default_factory=dict` erases the value type."""
    return {}


@dataclass
class EvalTask:
    """One eval case — a prompt with expected behavioral outcomes.

    *setup* is a dict of ``path → content`` to create before the task runs.
    *tags* are free-form category labels (e.g. ``["groom", "redact"]``).
    """

    id: str
    description: str
    prompt: str
    assertions: list[Assertion]  # at least one required
    tags: list[str] = field(default_factory=_empty_str_list)
    setup: dict[str, str] = field(default_factory=_empty_str_dict)

    @property
    def assertion_count(self) -> int:
        return len(self.assertions)


@dataclass
class EvalResult:
    """The outcome of running one eval task (produced by the runner)."""

    task_id: str
    passed: bool
    assertion_results: list[AssertionResult]
    duration_ms: float
    trace: list[str] = field(default_factory=_empty_str_list)


# ---------------------------------------------------------------------------
# JSON loader
# ---------------------------------------------------------------------------

# Fields that are valid at the top level of a task JSON file.
_VALID_TASK_FIELDS: frozenset[str] = frozenset({
    "id", "description", "prompt", "assertions", "tags", "setup",
})


def load_task(path: Path) -> EvalTask:
    """Load a single eval task from a JSON file.

    Validates:
    - The file is valid JSON
    - Required fields (id, description, prompt, assertions) are present
    - No unknown top-level fields
    - assertions is a non-empty list of valid assertion dicts

    Returns an ``EvalTask``.
    """
    try:
        parsed: object = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid JSON in {path}: {exc}") from exc

    if not isinstance(parsed, dict):
        raise ValueError(f"Task file {path} must contain a JSON object")
    # Validated above; trust the object's shape from here (untyped JSON data).
    raw = cast("dict[str, object]", parsed)

    # Unknown fields
    extra = set(raw) - _VALID_TASK_FIELDS
    if extra:
        raise ValueError(f"Unknown field(s) in {path}: {sorted(extra)}")

    # Required fields
    for required_field in ("id", "description", "prompt", "assertions"):
        if required_field not in raw:
            raise ValueError(
                f"Missing required field {required_field!r} in {path}"
            )

    # Assertions validation
    raw_assertions = raw["assertions"]
    if not isinstance(raw_assertions, list):
        raise ValueError(
            f"'assertions' must be a list in {path}, "
            f"got {type(raw_assertions).__name__}"
        )
    if not raw_assertions:
        raise ValueError(
            f"Task {path} has no assertions "
            f"(at least one assertion required)"
        )

    assertions: list[Assertion] = []
    assertion_items = cast("list[object]", raw_assertions)
    for i, a in enumerate(assertion_items):
        if not isinstance(a, dict):
            raise ValueError(
                f"Assertion {i} in {path} must be a dict, got {type(a).__name__}"
            )
        adict = cast("dict[str, object]", a)
        kind = adict.get("kind", "")
        if kind not in VALID_ASSERTION_KINDS:
            raise ValueError(
                f"Unknown assertion kind {kind!r} at index {i} in {path}. "
                f"Valid: {sorted(VALID_ASSERTION_KINDS)}"
            )
        target = adict.get("target", "")
        expected = adict.get("expected", "")
        if not target:
            raise ValueError(f"Assertion {i} in {path} missing 'target'")
        assertions.append(
            Assertion(kind=str(kind), target=str(target), expected=str(expected))
        )

    return EvalTask(
        id=str(raw["id"]),
        description=str(raw["description"]),
        prompt=str(raw["prompt"]),
        assertions=assertions,
        tags=cast("list[str]", raw.get("tags", [])),
        setup=cast("dict[str, str]", raw.get("setup", {})),
    )


def load_all_tasks(directory: Path) -> list[EvalTask]:
    """Load every ``*.json`` file in *directory* as an ``EvalTask``.

    Files are sorted by task id.  Invalid files are skipped silently
    (logged to stderr) — a single broken task doesn't block the suite.
    """
    if not directory.is_dir():
        return []

    tasks: list[EvalTask] = []
    for entry in sorted(directory.iterdir(), key=lambda p: p.name):
        if entry.suffix != ".json":
            continue
        try:
            tasks.append(load_task(entry))
        except (ValueError, FileNotFoundError):
            # A single invalid file should not block the suite — it will be
            # reported by the runner when it can't load it.
            import sys

            print(
                f"WARNING: skipping invalid eval task {entry.name}",
                file=sys.stderr,
            )

    tasks.sort(key=lambda t: t.id)
    return tasks
