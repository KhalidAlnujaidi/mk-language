"""Beacon's challenge set — winnable *via the AIOS Bible*.

The governed loop only books a finding when a failing challenge flips to pass
after the proposer consults the Bible. So the challenges must be answerable from
AIOS content (``cheatcodes/AIOS``): the agent fails at baseline (it doesn't know
AIOS), the proposer retrieves the real AIOS passage and writes a skill stating
the fact, and the scorer — reading that skill — passes. That makes "consult AIOS
→ produce benefit" measurable, one challenge climbed per successful cycle.

Regexes are deliberately loose (a correct answer phrased any way passes) but
specific enough that a wrong/empty answer fails. All facts are verbatim-grounded
in ``cheatcodes/AIOS/README.md``.
"""

from __future__ import annotations

from products.evolve.challenge import Challenge

BEACON_CHALLENGES: tuple[Challenge, ...] = (
    Challenge(
        id="aios-name",
        prompt=(
            "In the AIOS project, what does the acronym AIOS "
            "stand for? Answer in a few words."
        ),
        expect=(
            r"(ai|llm|artificial intelligence)"
            r"[\w ]{0,20}agent operating system"
            r"|agent operating system"
        ),
    ),
    Challenge(
        id="aios-kernel-role",
        prompt=(
            "In AIOS, the AIOS Kernel acts as what, "
            "with respect to the operating-system kernel?"
        ),
        expect=r"abstraction layer",
    ),
    Challenge(
        id="aios-memory-manager",
        prompt=(
            "Which AIOS kernel component is responsible for "
            "managing agent memory?"
        ),
        expect=r"memory manager",
    ),
    Challenge(
        id="aios-tool-manager",
        prompt=(
            "Name the AIOS kernel component that manages "
            "tools for agents."
        ),
        expect=r"tool manager",
    ),
    Challenge(
        id="aios-sdk",
        prompt=(
            "What is the name of the AIOS SDK "
            "(the companion repository to the AIOS kernel)?"
        ),
        expect=r"cerebrum",
    ),
    Challenge(
        id="aios-conference",
        prompt=(
            "The foundational AIOS paper was accepted by "
            "which conference in 2025? Give the acronym."
        ),
        expect=r"\bcolm\b",
    ),
)
