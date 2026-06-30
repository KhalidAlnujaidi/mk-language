#!/usr/bin/env python3
"""Generate the swarm job list for vision.md §8.3 — the golden eval set.

Each job asks one node to draft a *behavioral* pytest eval case (assert what the
system DID, not exact output) for one kernel/groom dimension. The real public API
and the governing theses are inlined so the context-blind inference nodes produce
code that targets the actual contracts. Output -> eval_jobs.json for swarm.py.

The swarm only DRAFTS. The home box curates + runs TDD before anything is committed.
"""

import json

PREAMBLE = """\
You are writing a behavioral regression test for `kinox`, a governed local-agent \
workspace. Rules that the code under test obeys:
- Thesis #1: ground truth beats the model — ground-truth tasks run as plain code, \
no model call.
- Thesis #2: fail-direction is per-component — guards fail CLOSED (deny on doubt), \
optimizers fail SOFT (pass through).
- Thesis #3: a missing capability is `null` (unknown), never a fabricated `False`.
Write a SELF-CONTAINED pytest test (assertions on behavior, not exact strings where \
a range is acceptable). Use the EXACT API below. Output ONLY one ```python code \
block — no prose, no explanation.
"""

DIMENSIONS = [
    (
        "redact",
        """\
from products.groom.stages.redact import redact, RedactResult, FAIL_DIRECTION
from kernel.contracts import FailDirection
# redact(text) -> RedactResult(text:str, found:tuple[str,...])
# Replaces each secret with «REDACTED:{kind}». kinds: anthropic_key (sk-ant-...),
# openai_key (sk-...), aws_key (AKIA + 16 upper/digits), generic_hex_token (>=32 hex).
# FAIL_DIRECTION is FailDirection.CLOSED.
Assert: a prompt containing an AWS key 'AKIA' + 16 chars is redacted, the original
key no longer appears in result.text, 'aws_key' is in result.found, and a
secret-free string passes through unchanged with empty found.""",
    ),
    (
        "router_ground_truth",
        """\
from kernel.contracts import Task, TaskKind, Tier
from kernel.router import route
from kernel.manifest import probe
# route(task, manifest) -> Tier | None
# GROUND_TRUTH kinds (REDACT/EXPAND/CONTEXT) must route to Tier.deterministic()
#   (Tier.is_model is False). TAG is the only FUZZY kind.
Assert: route(Task(TaskKind.REDACT), probe()) returns a Tier with is_model False.""",
    ),
    (
        "task_contract",
        """\
import pytest
from kernel.contracts import Task, TaskKind
# Task(kind, length_estimate=0, required_capabilities=frozenset(), budget_ms=None)
# FUZZY task (TaskKind.TAG) WITHOUT budget_ms -> raises ValueError.
# GROUND_TRUTH task (TaskKind.REDACT) WITH budget_ms set -> raises ValueError.
Assert both ValueError conditions with pytest.raises, and that a valid
Task(TaskKind.TAG, budget_ms=500) constructs without error.""",
    ),
    (
        "corrections",
        """\
from kernel.corrections import looks_like_correction, MAX_CORRECTION_WORDS
# looks_like_correction(prev_prompt, next_prompt) -> bool. True iff prev non-empty,
# next (stripped/lowercased) starts with a cue on a word/punct boundary
# (no/actually/i meant/not/wrong/nope/i said), and next has <= 12 words.
Assert: ('add a button','no, make it red') is True; ('add a button','nominal
spacing tweak') is False (cue must be on a boundary); a >12-word next is False;
empty prev is False.""",
    ),
    (
        "manifest_null",
        """\
from kernel.manifest import probe, Manifest, LocalModel
# probe() -> Manifest. A missing capability/probe is None (null), never False/0.
# Manifest.available_tiers() returns local-model tiers smallest-VRAM-first, then
# a cloud tier ONLY if a cloud key exists.
Assert: probe() returns a Manifest; any unknown numeric probe field is None rather
than a fabricated 0/False; available_tiers() is a tuple and every model tier with
where=='local' precedes any where=='cloud' tier.""",
    ),
    (
        "event_record",
        """\
from kernel.contracts import EventRecord
# EventRecord(task_id, kind, tier, tokens_in=None, tokens_out=None,
#   tokens_exact=False, latency_ms=None, correction_of=None)
# .as_correction_of(prior_task_id) -> copy with correction_of set.
Assert: a fresh EventRecord has correction_of None and tokens_exact False (never
claim cloud counts exact); .as_correction_of('t-1') returns a record whose
correction_of == 't-1' and leaves the original unchanged (frozen).""",
    ),
    (
        "annotation_halt",
        """\
from kernel.contracts import Annotation
# Annotation(lines=[], block=None). halt(reason) sets block; passthrough(lines)
# leaves block None. is_blocked is True iff block is not None. block is the ONLY
# halt mechanism.
Assert: Annotation.halt('secret found').is_blocked is True and .block carries the
reason; Annotation.passthrough(['ctx']).is_blocked is False and keeps the lines.""",
    ),
    (
        "groom_pipeline",
        """\
import tempfile, pathlib
from products.groom.pipeline import groom
from kernel.manifest import probe
from kernel.metrics import MetricsSink
# groom(prompt, *, manifest, sink, cwd, task_id) -> Annotation. Runs 4 stages
# (redact, expand, context, tag) and records EXACTLY ONE EventRecord per stage.
Assert: grooming a prompt that contains a secret writes 4 EventRecords to the
sink (one per stage) and the returned Annotation's lines mention a redaction.
Use tmp paths for the sink file and cwd.""",
    ),
    (
        "metrics_sink",
        """\
import tempfile, pathlib
from kernel.metrics import MetricsSink
from kernel.contracts import EventRecord
# MetricsSink(path): .record(event) appends; .read_all() -> list[EventRecord];
# .last() -> most recent EventRecord or None. Append-only JSONL.
Assert: recording two distinct EventRecords then read_all() returns both in order,
last() equals the second, and a fresh sink's last() is None. Use a tmp path.""",
    ),
    (
        "tier_factory",
        """\
import pytest
from kernel.contracts import Tier
# Tier.deterministic() -> is_model False. Tier.model(name, where='local'|'cloud').
# Unknown `where` raises ValueError.
Assert: Tier.deterministic().is_model is False; Tier.model('x', where='local')
has model_name 'x' and where 'local'; Tier.model('x', where='nope') raises
ValueError.""",
    ),
]


def main() -> None:
    jobs = []
    for key, api in DIMENSIONS:
        prompt = f"{PREAMBLE}\n# === API for this test ({key}) ===\n{api}\n"
        jobs.append({"id": f"eval-{key}", "prompt": prompt})
    out = "deploy/swarm/eval_jobs.json"
    with open(out, "w") as fh:
        json.dump(jobs, fh, indent=2)
    print(f"wrote {len(jobs)} jobs -> {out}")


if __name__ == "__main__":
    main()
