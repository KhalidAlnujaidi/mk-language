"""Eval task schema — behavioral assertions for the golden eval set (TASK-5-1).

Defines ``EvalTask`` (a single eval case), ``EvalResult`` (the outcome of
running one), and the JSON loader.  Tasks are stored as ``*.json`` files in
``evals/tasks/`` — stdlib ``json``, zero dependencies.

A kinox eval task is NOT exact-output matching.  It is a **behavioral
assertion**: "under these conditions, did the system do the right thing?"

DeepEval cheats harvested (see cheatcodes/cheats.md):
  - #1: scored metrics (score, reason, threshold) — partial regressions visible
  - #2: cost + token accounting — kinox's cost thesis as a measured invariant
  - #3: judged (LLM-as-judge) — fills the fuzzy-eval gap
  - #5: tool_correctness, step_efficiency — measure what kinox governs
  - #6: leaked (PII leak-back) — closes the redaction loop
  - #8: redteam — adversarial guard tests
  - #2b: budget — cost/token ceiling as a gated assertion
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
    # --- original deterministic kinds ---
    "contains",      # target text contains expected substring
    "not_contains",  # target text does NOT contain expected substring
    "redacted",      # target text had a secret removed (expected = secret type)
    "routed",        # tier_where / tier_model_name matches expected
    "refused",       # destructive action was denied (expected = action verb)
    "schema",        # target output matches expected JSON schema shape
    # --- DeepEval cheats ---
    # Cheat #2b: budget — cost/token ceiling as a gated assertion
    "budget",        # target metric (cost_usd/tokens_in/tokens_out) <= expected
    # Cheat #3: judged — LLM-as-judge with plain-English criteria + threshold
    "judged",        # target text scored by a local judge model against expected
    # Cheat #5: agent-specific metrics
    "tool_correctness",  # tools_called set matches expected (comma-sep), deterministic
    "step_efficiency",   # step_count <= expected (fewer steps = better), deterministic
    # Cheat #6: leaked — PII/secret leak-back in responses (inverse of redacted)
    "leaked",        # target text must NOT contain expected secret pattern
    # Cheat #8: redteam — adversarial guard test (prompt injection, obfuscation)
    "redteam",       # annotation_lines must show refused/blocked for adversarial input
    # stop-slop harvest: slop — target text must be free of LLM "slop" tells
    "slop",          # target text must NOT contain slop phrasing (deterministic)
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

    *threshold* (cheat #1) is an optional 0–1 score bar for scored assertions
    (``judged``).  When set, the runner derives pass/fail from ``score >=
    threshold`` instead of a boolean check.
    """

    kind: str
    target: str
    expected: str
    threshold: float | None = None

    def __post_init__(self) -> None:
        if self.kind not in VALID_ASSERTION_KINDS:
            raise ValueError(
                f"Unknown assertion kind {self.kind!r}. "
                f"Valid: {sorted(VALID_ASSERTION_KINDS)}"
            )


@dataclass
class AssertionResult:
    """The outcome of a single assertion after running the task.

    Cheat #1 (scored metrics): *score* (0–1), *threshold*, and *reason* are
    first-class fields.  When a score is present, ``passed`` is *derived* —
    ``score >= threshold``.  This lets the evolution store detect partial
    regressions (score dropped 0.9→0.6) that a boolean delta is blind to.

    Defaults preserve backward compatibility: existing boolean assertions keep
    working with score=0.0, threshold=0.0, reason="".
    """

    kind: str
    target: str
    passed: bool
    expected: str
    actual: str
    # Cheat #1: scored metric fields
    score: float = 0.0        # 0.0–1.0; 0.0 = not scored (boolean assertion)
    threshold: float = 0.0    # the bar this score was compared against
    reason: str = ""          # human-readable explanation / judge rationale


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
    """The outcome of running one eval task (produced by the runner).

    Cheat #2 (cost + token accounting): *cost_usd*, *tokens_in*, and
    *tokens_out* are first-class fields.  kinox's entire thesis is cost
    efficiency — every eval result now carries the spend and token counts
    incurred, so cost discipline goes from hope to measured invariant.

    Defaults preserve backward compatibility: existing results keep working
    with cost_usd=0.0, tokens_in=0, tokens_out=0.
    """

    task_id: str
    passed: bool
    assertion_results: list[AssertionResult]
    duration_ms: float
    trace: list[str] = field(default_factory=_empty_str_list)
    # Cheat #2: cost + token accounting
    cost_usd: float = 0.0      # total LLM spend for this task, in USD
    tokens_in: int = 0         # total input tokens consumed
    tokens_out: int = 0        # total output tokens consumed


# ---------------------------------------------------------------------------
# JSON loader
# ---------------------------------------------------------------------------

# Fields that are valid at the top level of a task JSON file.
_VALID_TASK_FIELDS: frozenset[str] = frozenset({
    "id", "description", "prompt", "assertions", "tags", "setup",
})

# Fields that are valid inside an assertion dict.
_VALID_ASSERTION_FIELDS: frozenset[str] = frozenset({
    "kind", "target", "expected", "threshold",
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

    # Unknown top-level fields
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

        # Unknown assertion fields
        extra_a = set(adict) - _VALID_ASSERTION_FIELDS
        if extra_a:
            raise ValueError(
                f"Unknown assertion field(s) {sorted(extra_a)} "
                f"in assertion {i} in {path}"
            )

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

        # Cheat #1: optional threshold for scored assertions
        threshold_raw = adict.get("threshold")
        threshold: float | None = None
        if threshold_raw is not None:
            try:
                threshold = float(threshold_raw)
            except (TypeError, ValueError) as exc:
                raise ValueError(
                    f"Assertion {i} in {path}: threshold must be a number, "
                    f"got {threshold_raw!r}"
                ) from exc

        assertions.append(
            Assertion(
                kind=str(kind),
                target=str(target),
                expected=str(expected),
                threshold=threshold,
            )
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
