"""The governed self-evolution loop (vision §6).

One turn of Darwinian self-improvement, with the dangerous parts removed by
construction:

  baseline → pick a FAILING challenge → propose a new skill → ISOLATE it →
  re-score → SELECT (keep iff the target flips to pass AND nothing regresses) →
  accumulate.

Safety is structural, not hoped-for:
- The agent only ever writes a ``SKILL.md`` into an isolated temp dir; core code,
  the kernel, the tests, and these challenges are never in its write set.
- The selector (``products/evolve/challenge.py``) is deterministic code the agent
  cannot see or edit — so it cannot reward-hack, only actually improve.
- No test loads from ``.claude/skills``, so a kept skill cannot break the suite —
  "don't break things" holds by construction for knowledge-evolution.

``score`` and ``propose`` are injected so the selection logic is unit-tested with
fakes (no model, no network); the defaults wire the real agent + model.
"""

from __future__ import annotations

import tempfile
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from pathlib import Path

from kernel.contracts import Tier
from kernel.metrics import MetricsSink

from products.agent import (
    ToolRegistry,
    default_registry,
    project_root_guard,
    run_agent,
)
from products.agent.environment import build_axioms
from products.agent.loop import AGENT_SYSTEM_PROMPT
from products.capabilities.registry import CapabilityRegistry, load_skills
from products.evolve.challenge import Challenge, passed

#: Score one challenge against a toolset → did the agent pass? (injected in tests)
ScoreFn = Callable[[Challenge, ToolRegistry], Awaitable[bool]]
#: Propose a candidate skill for a failing challenge → (skill_name, SKILL.md text).
#: Return ``("", "")`` to abstain. (injected in tests)
ProposeFn = Callable[[Challenge], Awaitable["tuple[str, str]"]]


@dataclass
class EvolveReport:
    """The outcome of one evolution turn — the full audit trail of a generation."""

    baseline: dict[str, bool] = field(default_factory=dict[str, bool])
    target: str | None = None
    proposed_skill: str | None = None
    after: dict[str, bool] | None = None
    decision: str = ""  # all-pass | no-candidate | kept | rejected:*


def build_registry(
    skills_dir: Path, root: Path, *, allow_bash: bool = False
) -> ToolRegistry:
    """The agent's toolset for a given skill corpus — filesystem + skill bridge."""
    skills = CapabilityRegistry(load_skills(skills_dir))
    return default_registry(root, skills=skills, allow_bash=allow_bash)


def _mirror_with_candidate(
    base_skills_dir: Path, dest: Path, name: str, content: str
) -> None:
    """Build an isolated corpus = base skills (symlinked) + the candidate skill.

    Symlinks keep it cheap (no copy of the corpus); the candidate is a real file
    so ``load_skills`` reads it like any other skill.
    """
    dest.mkdir(parents=True, exist_ok=True)
    if base_skills_dir.is_dir():
        for child in base_skills_dir.iterdir():
            if child.is_dir():
                (dest / child.name).symlink_to(child)
    cand = dest / name
    cand.mkdir(parents=True, exist_ok=True)
    (cand / "SKILL.md").write_text(content, encoding="utf-8")


async def default_score(
    challenge: Challenge,
    registry: ToolRegistry,
    *,
    tier: Tier,
    sink: MetricsSink,
    root: Path,
    max_turns: int = 5,
) -> bool:
    """Run the agent on the challenge and check the answer against ground truth.

    The agent is scored under the **same governance a real project-scope session
    carries**: the operating axioms (``build_axioms`` — axioms only, never the
    framework internals) are injected as its preamble. Without this the loop would
    measure a counterfactual agent that never exists in production and "evolve"
    skills to re-teach axiom-level facts every real agent already knows — an
    unfaithful fitness signal. Knowledge genuinely missing from the axioms (e.g. a
    framework internal) is exactly what stays a failing target worth evolving.
    """
    result = await run_agent(
        challenge.prompt,
        tier=tier,
        registry=registry,
        sink=sink,
        task_id=f"eval-{challenge.id}-{uuid.uuid4().hex[:6]}",
        preamble=build_axioms(root),
        max_turns=max_turns,
        guard=project_root_guard(root),
    )
    return passed(challenge, result.final_text)


async def model_propose(
    challenge: Challenge,
    *,
    tier: Tier,
    sink: MetricsSink,
    root: Path,
) -> tuple[str, str]:
    """Ask the model to author a SKILL.md aimed at the failing challenge.

    The generator is deliberately allowed to be noisy — the selector decides
    whether the candidate actually helps. A frontmatter header is guaranteed so
    ``load_skills`` always registers it (a malformed body just fails to help and
    is rejected — fail-soft).
    """
    name = f"evolved-{challenge.id}"
    prompt = (
        "Write a concise Claude-Code SKILL.md that would help a coding agent "
        "correctly answer this question about the kinox project:\n\n"
        f"  {challenge.prompt}\n\n"
        "Return ONLY the skill body (markdown). State the factual answer plainly "
        "so an agent reading the skill learns it."
    )
    reg = default_registry(root)  # generation needs no tools
    result = await run_agent(
        prompt,
        tier=tier,
        registry=reg,
        sink=sink,
        task_id=f"propose-{challenge.id}-{uuid.uuid4().hex[:6]}",
        system_prompt=AGENT_SYSTEM_PROMPT,
        preamble=build_axioms(root),  # same project-scope governance as scoring
        max_turns=2,
    )
    body = result.final_text.strip()
    if not body:
        return ("", "")
    content = (
        f"---\nname: {name}\n"
        f"description: Learned answer for kinox challenge {challenge.id}.\n"
        "metadata:\n  origin: self-evolution\n---\n\n"
        f"{body}\n"
    )
    return (name, content)


async def evolve_once(
    *,
    challenges: tuple[Challenge, ...],
    base_skills_dir: Path,
    root: Path,
    score: ScoreFn,
    propose: ProposeFn,
    accept_into: Path | None = None,
) -> EvolveReport:
    """Run one governed evolution turn over *challenges*.

    *accept_into* is where a KEPT skill is written (e.g. ``.claude/skills``);
    ``None`` runs the turn without mutating the live corpus (dry run).
    """
    base_reg = build_registry(base_skills_dir, root)
    baseline = {c.id: await score(c, base_reg) for c in challenges}

    failing = [c for c in challenges if not baseline[c.id]]
    if not failing:
        return EvolveReport(baseline=baseline, decision="all-pass")
    target = failing[0]

    name, content = await propose(target)
    if not name:
        return EvolveReport(
            baseline=baseline, target=target.id, decision="no-candidate"
        )

    # ISOLATE: score the candidate in a throwaway corpus — never the live one.
    with tempfile.TemporaryDirectory() as tmp:
        cand_dir = Path(tmp) / "skills"
        _mirror_with_candidate(base_skills_dir, cand_dir, name, content)
        cand_reg = build_registry(cand_dir, root)
        after = {c.id: await score(c, cand_reg) for c in challenges}

    # SELECT: keep iff the target flipped to pass AND nothing else regressed.
    improved = after[target.id] and not baseline[target.id]
    regressed = [c.id for c in challenges if baseline[c.id] and not after[c.id]]
    if not improved:
        decision = "rejected:no-improvement"
    elif regressed:
        decision = f"rejected:regression({','.join(regressed)})"
    else:
        decision = "kept"
        if accept_into is not None:
            dst = accept_into / name
            dst.mkdir(parents=True, exist_ok=True)
            (dst / "SKILL.md").write_text(content, encoding="utf-8")

    return EvolveReport(
        baseline=baseline,
        target=target.id,
        proposed_skill=name,
        after=after,
        decision=decision,
    )
