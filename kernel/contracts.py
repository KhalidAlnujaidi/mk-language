"""The load-bearing kernel contracts (vision §4).

Pure, dependency-light, agent-agnostic data types. Everything else in the kernel
is built on these. They encode two theses directly:

  - thesis #2 (fail-direction is per-component) → ``FailDirection``
  - thesis #3 (the next-turn correction is a free label) → ``EventRecord.correction_of``
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from enum import Enum
from typing import Literal


def _no_caps() -> frozenset[str]:
    return frozenset()


def _no_lines() -> list[str]:
    return []

# --- Axis enums ---------------------------------------------------------------


class Determinism(Enum):
    """Whether a task has a ground truth (no model) or is genuinely fuzzy."""

    GROUND_TRUTH = "ground_truth"  # regex / AST / git / fs → plain code
    FUZZY = "fuzzy"  # intent / expansion / summary → smallest model that fits


class FailDirection(Enum):
    """How a gate behaves under doubt — declared per component (thesis #2)."""

    CLOSED = "closed"  # deny on doubt (guards)
    SOFT = "soft"  # pass through on doubt (optimizers)


class TaskKind(Enum):
    """A unit of work. Its determinism is intrinsic to the kind."""

    REDACT = ("redact", Determinism.GROUND_TRUTH)
    EXPAND = ("expand", Determinism.GROUND_TRUTH)
    CONTEXT = ("context", Determinism.GROUND_TRUTH)
    TAG = ("tag", Determinism.FUZZY)  # the ONE fuzzy groom step

    def __init__(self, label: str, determinism: Determinism) -> None:
        self._label = label
        self._determinism = determinism

    @property
    def determinism(self) -> Determinism:
        return self._determinism


# --- Task ---------------------------------------------------------------------


@dataclass(frozen=True)
class Task:
    """A request to do one thing. Routing is a function of these fields.

    ``budget_ms`` is required for FUZZY tasks (a model call must be capped) and
    forbidden for GROUND_TRUTH tasks (no model, nothing to cap).
    """

    kind: TaskKind
    length_estimate: int = 0
    required_capabilities: frozenset[str] = field(default_factory=_no_caps)
    budget_ms: int | None = None

    def __post_init__(self) -> None:
        if self.determinism is Determinism.FUZZY and self.budget_ms is None:
            raise ValueError(f"{self.kind.name} is fuzzy and must declare budget_ms")
        if self.determinism is Determinism.GROUND_TRUTH and self.budget_ms is not None:
            raise ValueError(f"{self.kind.name} is ground-truth; no budget_ms allowed")

    @property
    def determinism(self) -> Determinism:
        return self.kind.determinism


# --- Tier (the router's output) ----------------------------------------------

Location = Literal["local", "cloud"]
_VALID_LOCATIONS: frozenset[str] = frozenset({"local", "cloud"})


@dataclass(frozen=True)
class Tier:
    """Where and how a task gets executed. Construct via the factories."""

    is_model: bool
    model_name: str | None = None
    where: Location | None = None

    @classmethod
    def deterministic(cls) -> Tier:
        """Plain code — no model (thesis #1)."""
        return cls(is_model=False, model_name=None, where=None)

    @classmethod
    def model(cls, name: str, *, where: Location) -> Tier:
        if where not in _VALID_LOCATIONS:
            valid = sorted(_VALID_LOCATIONS)
            raise ValueError(f"unknown location {where!r}; want one of {valid}")
        return cls(is_model=True, model_name=name, where=where)


# --- Annotation (the groom output; the only halt path) -----------------------


@dataclass(frozen=True)
class Annotation:
    """Context to inject, plus the single way to halt the request.

    ``block`` is the *only* mechanism that stops a prompt; everything else is
    additive context in ``lines``.
    """

    lines: list[str] = field(default_factory=_no_lines)
    block: str | None = None

    @classmethod
    def passthrough(cls, lines: list[str] | None = None) -> Annotation:
        return cls(lines=list(lines or []), block=None)

    @classmethod
    def halt(cls, reason: str) -> Annotation:
        return cls(lines=[], block=reason)

    @property
    def is_blocked(self) -> bool:
        return self.block is not None


# --- EventRecord (one per boundary; honest observability) --------------------


@dataclass(frozen=True)
class EventRecord:
    """One record per boundary. ``correction_of`` is the free-label slot that
    must exist from commit one (thesis #3 / hard truth #4)."""

    task_id: str
    kind: str
    tier: str
    tokens_in: int | None = None
    tokens_out: int | None = None
    tokens_exact: bool = False  # never claim cloud counts are exact
    latency_ms: float | None = None
    correction_of: str | None = None

    def as_correction_of(self, prior_task_id: str) -> EventRecord:
        """Return a copy marked as correcting an earlier task."""
        return replace(self, correction_of=prior_task_id)
