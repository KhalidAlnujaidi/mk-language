"""Beacon — the 24/7 autonomous self-development harness + live dashboard.

The cluster workers (node1/2/3) run a governed self-evolution loop around the
clock. Beacon is the *window* onto that loop: every cycle pledges to the kinox
axioms (``vision.md``), consults the AIOS Bible (``cheatcodes/AIOS``) for
state-of-the-art self-development findings, runs one governed ``evolve_once``
turn against the cluster model, and records the outcome to an append-only
ledger. The dashboard reads that ledger and surfaces — green — anything of
benefit (kept evolutions), documents pitfalls so they are not repeated, and
shows fleet health.

Safety is inherited, not added: the evolution turn is governed by construction
(isolated SKILL.md write set, deterministic selector the model cannot see), so
running it free, 24/7, can only accumulate measured improvement — never breakage.
Kept skills land in a PRIVATE working corpus (``var/beacon/corpus``), never the
human ``.claude/skills``.
"""

from products.beacon.axioms import load_axioms, pledge
from products.beacon.bible import Bible
from products.beacon.ledger import Ledger

__all__ = ["Bible", "Ledger", "load_axioms", "pledge"]
