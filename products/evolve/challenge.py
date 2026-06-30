"""The fitness function for governed self-evolution (vision §6).

A :class:`Challenge` is a prompt plus a **regex over ground truth the agent never
sees** — the un-gameable selector that turns a noisy generator into hill-climbing
(thesis #1: the verifier is deterministic code, not a model judging a model). The
agent passes only by producing the right answer; it cannot weaken the test,
because the regex lives here, outside its reach.

The built-in challenges are grounded in kinox's own canonical docs (``vision.md``
/ ``README.md``), so a *useful* new skill — one that surfaces those truths — is
exactly what moves a fail to a pass. That is the loop's whole thesis made
measurable: knowledge added to the corpus shows up as fitness.
"""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class Challenge:
    """One scored task: ask *prompt*, pass iff *expect* matches the answer.

    *expect* is a case-insensitive regex searched against the agent's final
    text. Keep it tight enough that a wrong answer fails, loose enough that a
    right answer phrased differently still passes.
    """

    id: str
    prompt: str
    expect: str  # case-insensitive regex


def passed(challenge: Challenge, answer: str) -> bool:
    """True iff *answer* satisfies *challenge* — the entire selection signal."""
    return re.search(challenge.expect, answer, re.IGNORECASE) is not None


#: Default challenge set — answers are ground truth in vision.md / README.md, so
#: a skill that teaches the agent kinox's own axioms is the thing that passes them.
CHALLENGES: tuple[Challenge, ...] = (
    Challenge(
        id="guard-fail-direction",
        prompt=(
            "In kinox, when a guard is in doubt, does it fail OPEN or fail "
            "CLOSED? Answer with the single word."
        ),
        expect=r"\bclosed\b",
    ),
    Challenge(
        id="asymmetry-thesis",
        prompt=(
            "Kinox's first thesis: when a task has a ground truth (regex, AST, "
            "git, filesystem), what does the work — a model, or plain "
            "deterministic code?"
        ),
        expect=r"determinist|plain\s+code",
    ),
    Challenge(
        id="reserved-scope",
        prompt=(
            "Which short name is reserved as the kinox admin scope and "
            "blacklisted as a project name?"
        ),
        expect=r"\bkin\b",
    ),
)
