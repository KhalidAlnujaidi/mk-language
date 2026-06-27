"""Governed self-evolution — the higher-level loop that improves the agent.

A Darwinian turn: propose a skill for a failing challenge, isolate it, re-score
against a deterministic verifier, keep it only if it improves without regressing.
The agent's write set is one isolated SKILL.md; the selector and core are out of
its reach, so noise can only become measured improvement, never breakage.
"""

from products.evolve.challenge import CHALLENGES, Challenge, passed
from products.evolve.loop import (
    EvolveReport,
    build_registry,
    default_score,
    evolve_once,
    model_propose,
)

__all__ = [
    "CHALLENGES",
    "Challenge",
    "EvolveReport",
    "build_registry",
    "default_score",
    "evolve_once",
    "model_propose",
    "passed",
]
