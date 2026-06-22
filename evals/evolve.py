"""Gated self-evolving proposer (vision §6 proactive).

The capstone the §8.3 eval harness makes safe: a governed
observe → propose → validate → gate cycle. This is a deterministic stub — there
is NO live LLM and NO autonomous code change. Two rules are absolute:

  1. A proposal that touches **code** is never auto-applied — it is gated to a
     human (``requires_human``). Self-evolving config is fine; self-editing code
     is not (hard truth #2: evolve only what the eval set can measure + gate).
  2. A **config** proposal is auto-approved only when the golden eval set stays
     green and does not regress vs. the baseline.

Every decision records an evolution artifact (branch + eval diff) via
``evals.store.record_evolution``, so the trail is durable and auditable.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from products.feedback.review import ReviewItem

from evals.runner import EvalReport
from evals.store import record_evolution

#: Targets the proposer is allowed to touch automatically (config only).
SANCTIONED_TARGETS: frozenset[str] = frozenset({"groom.config", "prompt"})


@dataclass(frozen=True)
class Proposal:
    """A proposed change. ``kind`` is ``config`` (sanctioned) or ``code`` (gated)."""

    target: str
    change: str
    kind: str


@dataclass(frozen=True)
class Decision:
    """The gate's verdict on a proposal."""

    proposal: Proposal
    approved: bool
    requires_human: bool
    reason: str


def observe(items: list[ReviewItem]) -> list[ReviewItem]:
    """Pass-through over correction review items (most-corrected first)."""
    return sorted(items, key=lambda i: i.times_corrected, reverse=True)


def propose(items: list[ReviewItem]) -> Proposal | None:
    """Propose a sanctioned config tweak for the most-corrected area, or None."""
    ranked = observe(items)
    if not ranked:
        return None
    worst = ranked[0]
    return Proposal(
        target="groom.config",
        change=f"revisit handling of task {worst.prior_task_id} "
        f"({worst.times_corrected} corrections)",
        kind="config",
    )


def gate(
    proposal: Proposal,
    *,
    before: EvalReport,
    after: EvalReport,
    evolutions_dir: str | Path,
    eval_id: str,
) -> Decision:
    """Decide a proposal and record the evolution artifact.

    Code proposals (or non-sanctioned targets) → human-gated, never auto-applied.
    Config proposals → approved only if the eval set stays green and does not
    regress.
    """
    record_evolution(
        evolutions_dir,
        eval_id=eval_id,
        branch=f"evolve/{eval_id}",
        before=before,
        after=after,
        notes=f"{proposal.kind}:{proposal.target} — {proposal.change}",
    )

    if proposal.kind == "code" or proposal.target not in SANCTIONED_TARGETS:
        return Decision(
            proposal,
            approved=False,
            requires_human=True,
            reason="touches code / non-sanctioned target — needs human approval",
        )

    if not after.ok or after.failed > before.failed:
        return Decision(
            proposal,
            approved=False,
            requires_human=False,
            reason="rejected — eval set regressed",
        )

    return Decision(
        proposal,
        approved=True,
        requires_human=False,
        reason="auto-approved — sanctioned config change, eval set green",
    )
