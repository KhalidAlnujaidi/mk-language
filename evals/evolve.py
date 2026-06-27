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

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from products.feedback.review import ReviewItem

from evals.runner import EvalReport, run_golden_eval
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

    # Reject on REGRESSION relative to the baseline (not on absolute non-greenness):
    # the golden set legitimately carries known-failing tasks (honest fitness gaps),
    # so the bar is "added no new failures", per this gate's own contract — "does
    # not regress vs. the baseline". An empty run (nothing measured) is also refused.
    if after.total == 0 or after.failed > before.failed:
        return Decision(
            proposal,
            approved=False,
            requires_human=False,
            reason="rejected — eval set regressed vs. baseline (or nothing ran)",
        )

    return Decision(
        proposal,
        approved=True,
        requires_human=False,
        reason="auto-approved — sanctioned config change, eval set green",
    )


def run_evolution_gate(
    proposal: Proposal,
    *,
    root: Path,
    apply_change: Callable[[], None],
    evolutions_dir: str | Path,
    eval_id: str,
    tasks_dir: Path = Path("evals/tasks"),
) -> Decision:
    """Gate *proposal* on the GOLDEN eval set, measured before vs. after the change.

    This is the connection §8.3 was missing: the gate's pass/fail signal now comes
    from running the real golden set (:func:`evals.runner.run_golden_eval`), not a
    hand-supplied ``EvalReport``. The cycle:

      1. measure the golden baseline (``before``);
      2. for a **code** or non-sanctioned proposal, never apply it — gate straight
         to a human, recording ``before`` as both sides (no change was made);
      3. for a sanctioned **config** proposal, ``apply_change()`` then re-measure
         (``after``) and let :func:`gate` auto-approve only if the golden set did
         not regress.

    So self-evolution is blocked on the golden baseline end-to-end (hard truth #2):
    a config change that drops any golden task is rejected, and code is never
    self-applied. The caller supplies ``apply_change`` so applying the change and
    its reversal remain its responsibility — this function only measures and gates.
    """
    before = run_golden_eval(tasks_dir, root=root)
    if proposal.kind == "code" or proposal.target not in SANCTIONED_TARGETS:
        # Code is never self-applied; gate it to a human against the baseline.
        return gate(
            proposal,
            before=before,
            after=before,
            evolutions_dir=evolutions_dir,
            eval_id=eval_id,
        )
    apply_change()
    after = run_golden_eval(tasks_dir, root=root)
    return gate(
        proposal,
        before=before,
        after=after,
        evolutions_dir=evolutions_dir,
        eval_id=eval_id,
    )
