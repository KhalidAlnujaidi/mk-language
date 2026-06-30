"""The governed evolution loop — selection logic, proven with fakes (no model).

The agent/model is faked; what's under test is the GOVERNANCE: a candidate is
kept only when it flips the target to pass with no regression, is isolated during
scoring, and is written to the live corpus only when kept.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any, TypeVar

import pytest
from kernel.contracts import Tier
from kernel.metrics import MetricsSink
from products.agent import ToolRegistry
from products.agent.loop import AgentResult
from products.evolve import Challenge, evolve_once
from products.evolve.loop import default_score, model_propose

_T = TypeVar("_T")


def _run(coro: Awaitable[_T]) -> _T:
    return asyncio.run(coro)  # type: ignore[arg-type]


A = Challenge(id="a", prompt="qa", expect="x")
B = Challenge(id="b", prompt="qb", expect="x")


def _score_factory(
    rule: Callable[[str, bool], bool],
) -> Callable[[Challenge, ToolRegistry], Awaitable[bool]]:
    """A fake scorer that distinguishes baseline from candidate the real way —
    by asking the registry whether the evolved skill is present in the corpus."""

    async def score(challenge: Challenge, registry: ToolRegistry) -> bool:
        found = registry.dispatch("find_skill", '{"query": "evolved"}')
        has_candidate = "evolved-" in found
        return rule(challenge.id, has_candidate)

    return score


def _propose_ok(challenge: Challenge) -> Callable[..., Awaitable[tuple[str, str]]]:
    name = f"evolved-{challenge.id}"

    async def propose(_c: Challenge) -> tuple[str, str]:
        return (
            name,
            f"---\nname: {name}\ndescription: learned answer\n"
            "metadata:\n  origin: test\n---\n\nThe answer.\n",
        )

    return propose


async def _propose_abstain(_c: Challenge) -> tuple[str, str]:
    return ("", "")


def _dirs(tmp_path: Path) -> tuple[Path, Path]:
    base = tmp_path / "base"
    base.mkdir()
    return base, tmp_path  # (empty base corpus, root)


def test_all_pass_skips_proposal(tmp_path: Path) -> None:
    base, root = _dirs(tmp_path)
    report = _run(
        evolve_once(
            challenges=(A, B),
            base_skills_dir=base,
            root=root,
            score=_score_factory(lambda _cid, _has: True),
            propose=_propose_abstain,
        )
    )
    assert report.decision == "all-pass"
    assert report.after is None


def test_keeps_a_real_improvement(tmp_path: Path) -> None:
    base, root = _dirs(tmp_path)
    accept = tmp_path / "live"
    accept.mkdir()
    # Fails at baseline, passes once the evolved skill is in the corpus.
    report = _run(
        evolve_once(
            challenges=(A, B),
            base_skills_dir=base,
            root=root,
            score=_score_factory(lambda _cid, has: has),
            propose=_propose_ok(A),
            accept_into=accept,
        )
    )
    assert report.decision == "kept"
    # The kept skill is written into the live corpus (the archive grows).
    assert (accept / "evolved-a" / "SKILL.md").is_file()


def test_rejects_no_improvement(tmp_path: Path) -> None:
    base, root = _dirs(tmp_path)
    report = _run(
        evolve_once(
            challenges=(A, B),
            base_skills_dir=base,
            root=root,
            score=_score_factory(lambda _cid, _has: False),  # never passes
            propose=_propose_ok(A),
        )
    )
    assert report.decision == "rejected:no-improvement"


def test_rejects_regression(tmp_path: Path) -> None:
    base, root = _dirs(tmp_path)
    # Candidate flips A to pass but breaks B (which passed at baseline).
    def rule(cid: str, has: bool) -> bool:
        if cid == "a":
            return has
        return not has  # B passes only WITHOUT the candidate → regression

    report = _run(
        evolve_once(
            challenges=(A, B),
            base_skills_dir=base,
            root=root,
            score=_score_factory(rule),
            propose=_propose_ok(A),
        )
    )
    assert report.decision.startswith("rejected:regression")
    assert "b" in report.decision


def test_no_candidate_when_generator_abstains(tmp_path: Path) -> None:
    base, root = _dirs(tmp_path)
    report = _run(
        evolve_once(
            challenges=(A, B),
            base_skills_dir=base,
            root=root,
            score=_score_factory(lambda _cid, _has: False),
            propose=_propose_abstain,
        )
    )
    assert report.decision == "no-candidate"


def test_rejected_candidate_never_touches_live_corpus(tmp_path: Path) -> None:
    base, root = _dirs(tmp_path)
    accept = tmp_path / "live"
    accept.mkdir()
    _run(
        evolve_once(
            challenges=(A, B),
            base_skills_dir=base,
            root=root,
            score=_score_factory(lambda _cid, _has: False),  # rejected
            propose=_propose_ok(A),
            accept_into=accept,
        )
    )
    # Nothing written — isolation held; only KEPT skills reach the live corpus.
    assert list(accept.iterdir()) == []


# --- eval-fidelity: the scored agent runs under real project-scope governance ---


def _root_with_axioms(tmp_path: Path, marker: str) -> Path:
    """A root whose alignment/AXIOMS.md carries *marker* so a preamble built from
    it is identifiable when captured."""
    (tmp_path / "alignment").mkdir()
    (tmp_path / "alignment" / "AXIOMS.md").write_text(
        f"# Operating axioms\n\n{marker}\n", encoding="utf-8"
    )
    return tmp_path


def _capture_run_agent(
    monkeypatch: pytest.MonkeyPatch, answer: str
) -> dict[str, Any]:
    """Replace ``run_agent`` in the evolve loop with a spy that records its kwargs
    and returns a fixed answer — no model, no network."""
    seen: dict[str, Any] = {}

    async def fake_run_agent(_task: str, **kwargs: Any) -> AgentResult:
        seen.update(kwargs)
        return AgentResult(final_text=answer)

    monkeypatch.setattr("products.evolve.loop.run_agent", fake_run_agent)
    return seen


def test_default_score_injects_axioms_preamble(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The scored agent must carry the operating axioms, exactly as a real
    # project-scope session does — otherwise the fitness signal is unfaithful.
    root = _root_with_axioms(tmp_path, "AXIOM-MARKER-SCORE")
    seen = _capture_run_agent(monkeypatch, answer="closed")
    ok = _run(
        default_score(
            Challenge(id="c", prompt="open or closed?", expect=r"closed"),
            ToolRegistry(),
            tier=Tier.model("m", where="local", backend="ollama"),
            sink=MetricsSink(Path("/dev/null")),
            root=root,
        )
    )
    assert ok is True
    assert "AXIOM-MARKER-SCORE" in seen["preamble"]


def test_model_propose_injects_axioms_preamble(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The generator runs under the same project-scope governance as scoring.
    root = _root_with_axioms(tmp_path, "AXIOM-MARKER-PROPOSE")
    seen = _capture_run_agent(monkeypatch, answer="the answer body")
    name, content = _run(
        model_propose(
            Challenge(id="c", prompt="teach it", expect="x"),
            tier=Tier.model("m", where="local", backend="ollama"),
            sink=MetricsSink(Path("/dev/null")),
            root=root,
        )
    )
    assert name == "evolved-c" and "the answer body" in content
    assert "AXIOM-MARKER-PROPOSE" in seen["preamble"]
