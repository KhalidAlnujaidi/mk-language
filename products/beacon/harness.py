"""The 24/7 autonomous self-development loop, run against the cluster.

One cycle = pledge (periodically) → consult the AIOS Bible → run one governed
``evolve_once`` turn on the cluster model → record the outcome (finding / pitfall
/ corpus_hit / health) to the ledger. The loop runs forever, backing off to a
long idle beat when there is nothing left to improve ("as long as they produce
benefit, let them run"). Kept skills accumulate in a PRIVATE working corpus, so
the human ``.claude/skills`` is never mutated by the machine.

Model routing: the cluster is just an Ollama endpoint, so we point kinox's broker
at the Service VIP via ``KINOX_OLLAMA_URL`` and use a ``where="local"`` /
``backend="ollama"`` tier — no new transport (Rule Zero; the broker already
speaks OpenAI-compatible).
"""

from __future__ import annotations

import asyncio
import contextlib
import functools
import os
import time
from pathlib import Path

from daemon.brain import brain_tier
from kernel.contracts import Tier
from kernel.metrics import MetricsSink

from products.agent import ToolRegistry
from products.agent.loop import run_agent
from products.beacon.axioms import load_axioms, pledge
from products.beacon.bible import Bible
from products.beacon.challenges import BEACON_CHALLENGES
from products.beacon.ledger import Ledger, resume_state
from products.evolve import EvolveReport, default_score, evolve_once
from products.evolve.challenge import Challenge

# --- Paths & config (repo-rooted; overridable by env) -------------------------

REPO = Path(__file__).resolve().parents[2]
VAR = REPO / "var" / "beacon"
LEDGER_PATH = VAR / "ledger.jsonl"
METRICS_PATH = VAR / "metrics.jsonl"
CORPUS = VAR / "corpus"  # private, cumulative working corpus (never .claude/skills)
SKILLS = REPO / ".claude" / "skills"
AIOS = REPO / "cheatcodes" / "AIOS"
VISION = REPO / "vision.md"

MODEL = os.environ.get("KINOX_BEACON_MODEL", "qwen2.5:3b")
# The durable cluster inference Service (deploy/cluster/ollama-daemonset.yaml).
CLUSTER_URL = "http://10.43.33.57:11434/v1"
CLUSTER_TIER = Tier.model(MODEL, where="local", backend="ollama")
# The generative brain. ``KINOX_BRAIN`` (e.g. ``glm-5.2`` on z.ai) promotes a
# frontier model to author the candidate skills; the cheap cluster model stays
# the VERIFIER (``default_score`` below) and the fail-soft fallback — the
# expensive model does only the high-value generation (thesis #1).
BRAIN_TIER = brain_tier(fallback=CLUSTER_TIER) or CLUSTER_TIER

PLEDGE_EVERY = 20  # re-affirm the axioms every N cycles
BUSY_SLEEP_S = 5.0  # pause between productive cycles
IDLE_SLEEP_S = 300.0  # back off when nothing is failing (still alive, low cost)
IDLE_AFTER = 3  # consecutive all-pass cycles before idling


def _ensure_cluster_endpoint() -> str:
    """Point the broker at the cluster unless the operator already set a URL."""
    url = os.environ.get("KINOX_OLLAMA_URL")
    if not url:
        os.environ["KINOX_OLLAMA_URL"] = CLUSTER_URL
        url = CLUSTER_URL
    return url


def seed_corpus(base: Path, dest: Path) -> None:
    """Seed the private working corpus from *base* by symlinking each skill in.

    Idempotent: existing entries are left alone, so kept skills from prior runs
    survive. Symlinks keep it cheap — no copy of the human corpus.
    """
    dest.mkdir(parents=True, exist_ok=True)
    if not base.is_dir():
        return
    for child in base.iterdir():
        link = dest / child.name
        if not link.exists():
            with contextlib.suppress(OSError):
                link.symlink_to(child)


def _bible_propose(bible: Bible, ledger: Ledger, sink: MetricsSink):
    """A proposer that consults the AIOS Bible, cites it, then authors a SKILL.md.

    Mirrors ``evolve.model_propose`` but injects the most relevant AIOS passage
    as reference material and records a ``corpus_hit`` when the Bible is used —
    Rule Zero made measurable.
    """

    async def propose(challenge: Challenge) -> tuple[str, str]:
        name = f"evolved-{challenge.id}"
        passages = bible.consult(challenge.prompt, k=2)
        reference = ""
        if passages:
            ledger.record(
                "corpus_hit",
                challenge=challenge.id,
                bible=bible.name,
                sources=[p.source for p in passages],
            )
            joined = "\n\n".join(f"[{p.source}]\n{p.text}" for p in passages)
            reference = (
                f"\n\nReference findings from the {bible.name} Bible "
                f"(reuse what fits, Rule Zero):\n{joined}\n"
            )
        prompt = (
            "Write a concise Claude-Code SKILL.md that would help a coding agent "
            "correctly answer this question about the kinox project:\n\n"
            f"  {challenge.prompt}\n{reference}\n"
            "Return ONLY the skill body (markdown). State the factual answer plainly "
            "so an agent reading the skill learns it."
        )
        # Generation needs NO tools — a tool schema makes a small model try to
        # call tools instead of writing prose (and abstain). Plain chat instead.
        result = await run_agent(
            prompt,
            tier=BRAIN_TIER,
            registry=ToolRegistry(),
            sink=sink,
            task_id=f"propose-{challenge.id}",
            system_prompt="You write concise, factual Claude-Code skill documents.",
            max_turns=1,
            fallback=CLUSTER_TIER,
        )
        body = result.final_text.strip()
        if not body or body.startswith("(model unavailable"):
            return ("", "")
        content = (
            f"---\nname: {name}\n"
            f"description: Learned answer for kinox challenge {challenge.id}.\n"
            "metadata:\n  origin: beacon-self-evolution\n"
            f"  bible: {bible.name}\n---\n\n{body}\n"
        )
        return (name, content)

    return propose


def _tps_since(sink: MetricsSink, start_idx: int) -> tuple[float | None, int]:
    """Tokens/sec across model turns recorded since *start_idx* (and new count)."""
    events = sink.read_all()
    fresh = events[start_idx:]
    toks = sum(e.tokens_out or 0 for e in fresh if e.kind == "agent")
    secs = sum((e.latency_ms or 0) / 1000.0 for e in fresh if e.kind == "agent")
    tps = (toks / secs) if secs > 0 else None
    return tps, len(events)


async def run_cycle(
    cycle: int,
    *,
    ledger: Ledger,
    sink: MetricsSink,
    bible: Bible,
    started_at: float,
    challenges: tuple[Challenge, ...] = BEACON_CHALLENGES,
) -> EvolveReport:
    """Run one governed evolution turn and record everything it produced."""
    start_idx = len(sink.read_all())
    ledger.record("cycle", cycle=cycle, challenges=[c.id for c in challenges])

    score = functools.partial(default_score, tier=CLUSTER_TIER, sink=sink, root=REPO)
    propose = _bible_propose(bible, ledger, sink)

    try:
        report = await evolve_once(
            challenges=challenges,
            base_skills_dir=CORPUS,
            root=REPO,
            score=score,
            propose=propose,
            accept_into=CORPUS,
        )
    except Exception as exc:  # noqa: BLE001 — the loop must never die on one cycle
        ledger.record(
            "pitfall", cycle=cycle, kind_of="exception", cause=repr(exc)[:300]
        )
        raise

    # Interpret the governed decision into ledger signal.
    if report.decision == "kept":
        ledger.record(
            "finding",
            cycle=cycle,
            challenge=report.target,
            skill=report.proposed_skill,
            baseline=report.baseline,
            after=report.after,
            note="Kept evolution — fitness improved with no regression.",
        )
    elif report.decision == "all-pass":
        pass  # nothing failing this cycle — no benefit to book, not a pitfall
    elif report.decision.startswith("rejected") or report.decision == "no-candidate":
        ledger.record(
            "pitfall",
            cycle=cycle,
            challenge=report.target,
            kind_of=report.decision,
            cause=_pitfall_cause(report.decision),
        )

    tps, new_total = _tps_since(sink, start_idx)
    ledger.record(
        "health",
        cycle=cycle,
        decision=report.decision,
        baseline_pass=sum(1 for v in report.baseline.values() if v),
        baseline_total=len(report.baseline),
        corpus_skills=sum(1 for _ in CORPUS.iterdir()) if CORPUS.is_dir() else 0,
        tps=round(tps, 1) if tps is not None else None,
        model_turns=new_total - start_idx,
        uptime_s=round(time.time() - started_at, 1),
    )
    return report


def _pitfall_cause(decision: str) -> str:
    if decision == "no-candidate":
        return "Proposer abstained — model returned an empty skill body."
    if decision.startswith("rejected:regression"):
        return f"Candidate broke another challenge ({decision}); selector rejected it."
    if decision == "rejected:no-improvement":
        return "Candidate did not flip the target to pass; selector rejected it."
    return decision


async def run_once() -> EvolveReport:
    """Single governed cycle against the cluster — the harness smoke test."""
    _ensure_cluster_endpoint()
    VAR.mkdir(parents=True, exist_ok=True)
    seed_corpus(SKILLS, CORPUS)
    ledger = Ledger(LEDGER_PATH)
    sink = MetricsSink(METRICS_PATH)
    bible = Bible(AIOS)
    axioms = load_axioms(VISION)
    pledge(ledger, axioms, bible=bible.name, cycle=0)
    return await run_cycle(
        0, ledger=ledger, sink=sink, bible=bible, started_at=time.time()
    )


async def run_forever() -> None:
    """The 24/7 loop: pledge, evolve, record, repeat — idling when nothing fails."""
    _ensure_cluster_endpoint()
    VAR.mkdir(parents=True, exist_ok=True)
    seed_corpus(SKILLS, CORPUS)
    ledger = Ledger(LEDGER_PATH)
    sink = MetricsSink(METRICS_PATH)
    bible = Bible(AIOS)
    axioms = load_axioms(VISION)

    # Resume from the ledger, not from zero: a restart continues the same
    # generation count and uptime instead of duplicating cycle numbers in the
    # append-only history the dashboard reads. Empty ledger → a cold start.
    state = resume_state(ledger)
    started_at = time.time() - state.uptime_offset
    cycle = state.cycle
    idle_streak = state.idle_streak
    if cycle:
        ledger.record(
            "resume",
            cycle=cycle,
            idle_streak=idle_streak,
            uptime_offset_s=round(state.uptime_offset, 1),
        )

    while True:
        if cycle % PLEDGE_EVERY == 0:
            pledge(ledger, axioms, bible=bible.name, cycle=cycle)
        try:
            report = await run_cycle(
                cycle, ledger=ledger, sink=sink, bible=bible, started_at=started_at
            )
            # A KEPT evolution is the only "benefit produced"; anything else
            # (all-pass or rejection) counts toward backing off — run 24/7, but
            # don't thrash the same unsolvable challenge every few seconds.
            idle_streak = 0 if report.decision == "kept" else idle_streak + 1
        except Exception:  # noqa: BLE001 — already recorded as a pitfall; keep alive
            idle_streak += 1
        cycle += 1
        await asyncio.sleep(IDLE_SLEEP_S if idle_streak >= IDLE_AFTER else BUSY_SLEEP_S)


if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1 and sys.argv[1] == "once":
        report = asyncio.run(run_once())
        print(f"cycle decision: {report.decision}")
    else:
        asyncio.run(run_forever())
