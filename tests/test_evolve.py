"""Gated self-evolving proposer (vision §6 proactive).

observe → propose → validate → gate, deterministic stub. Hard rules: a proposal
that touches code is NEVER auto-applied (requires_human); a config proposal is
auto-approved ONLY if the golden eval set stays green (no regression). Every
decision writes an evolution artifact (branch + eval diff, §6/§8.3).
"""

from __future__ import annotations

import json
from pathlib import Path

from evals.evolve import Proposal, gate, propose
from evals.runner import EvalReport
from products.feedback.review import ReviewItem


def test_propose_targets_config_for_most_corrected_area():
    items = [ReviewItem("t-1", times_corrected=3, correcting_task_ids=("a", "b", "c"))]
    proposal = propose(items)
    assert proposal is not None
    assert proposal.kind == "config"  # never a code edit


def test_propose_returns_none_without_corrections():
    assert propose([]) is None


def test_green_config_proposal_is_auto_approved_and_recorded(tmp_path: Path):
    proposal = Proposal(target="groom.config", change="reorder stages", kind="config")
    before = EvalReport(total=27, passed=27, failed=0)
    after = EvalReport(total=27, passed=27, failed=0)
    decision = gate(
        proposal, before=before, after=after, evolutions_dir=tmp_path, eval_id="ev-1"
    )
    assert decision.approved is True
    assert decision.requires_human is False
    artifact = tmp_path / "ev-1.json"
    assert artifact.exists()
    assert json.loads(artifact.read_text())["gate_passed"] is True


def test_code_proposal_is_gated_to_human(tmp_path: Path):
    proposal = Proposal(target="kernel.router", change="tweak scoring", kind="code")
    rpt = EvalReport(total=27, passed=27, failed=0)
    decision = gate(
        proposal, before=rpt, after=rpt, evolutions_dir=tmp_path, eval_id="ev-2"
    )
    assert decision.requires_human is True
    assert decision.approved is False


def test_regressing_config_proposal_is_rejected(tmp_path: Path):
    proposal = Proposal(target="groom.config", change="risky reorder", kind="config")
    before = EvalReport(total=27, passed=27, failed=0)
    after = EvalReport(total=27, passed=25, failed=2)  # regression
    decision = gate(
        proposal, before=before, after=after, evolutions_dir=tmp_path, eval_id="ev-3"
    )
    assert decision.approved is False
    assert decision.requires_human is False
    assert "regress" in decision.reason.lower()
