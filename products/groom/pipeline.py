"""Squire grooming pipeline — composes the four stages in order.

Execution order:
    redact → expand → context → deslop → tag

Each stage emits exactly one ``EventRecord`` to the sink.  Tier strings:
    - ``"deterministic"``   for the three ground-truth stages
    - ``f"model:{tier.where}"`` for tag (actual routed tier)
    - ``"deterministic"``   for tag when router returns None

Returns an ``Annotation`` (``block`` stays ``None`` in M0 — redaction is total
so no blocking needed; the redacted context line communicates what happened).
"""

from __future__ import annotations

import time
from pathlib import Path

from kernel.contracts import Annotation, EventRecord, Tier
from kernel.manifest import Manifest
from kernel.metrics import MetricsSink

from products.groom import tag as tagmod
from products.groom.stages import context as context_stage
from products.groom.stages import deslop as deslop_stage
from products.groom.stages import expand as expand_stage
from products.groom.stages import redact as redact_stage
from products.groom.tag import ModelTag

_DETERMINISTIC_TIER: str = "deterministic"


def _tier_str(tier: Tier) -> str:
    """Convert a ``Tier`` to the canonical EventRecord tier string."""
    if not tier.is_model:
        return _DETERMINISTIC_TIER
    return f"model:{tier.where}"


def groom(
    prompt: str,
    *,
    manifest: Manifest,
    sink: MetricsSink,
    cwd: Path,
    task_id: str,
    model_tag: ModelTag | None = None,
) -> Annotation:
    """Run the four-stage squire pipeline and return an ``Annotation``.

    Stages:
        1. redact  — detect and replace secrets (CLOSED, ground-truth)
        2. expand  — resolve @-path mentions (SOFT, ground-truth)
        3. context — gather git/fs context lines (SOFT, ground-truth)
        4. tag     — fuzzy tag: real router call, optional local-model offload
                     via *model_tag*, SOFT fallback to keyword tags

    One ``EventRecord`` is written to *sink* per stage.  ``latency_ms`` is
    measured with ``time.perf_counter``.  ``tokens_exact=False`` on these
    boundary records (the offloaded model's own token usage is not yet folded in).
    """
    lines: list[str] = []

    # ------------------------------------------------------------------
    # Stage 1: redact
    # ------------------------------------------------------------------
    t0 = time.perf_counter()
    redact_result = redact_stage.redact(prompt)
    latency_redact = (time.perf_counter() - t0) * 1000.0

    sink.record(
        EventRecord(
            task_id=task_id,
            kind="redact",
            tier=_DETERMINISTIC_TIER,
            tokens_exact=False,
            latency_ms=latency_redact,
        )
    )

    # Carry the redacted text through the rest of the pipeline.
    working_text = redact_result.text

    if redact_result.found:
        kinds_str = ", ".join(redact_result.found)
        lines.append(f"groomed: redacted {kinds_str}")

    # ------------------------------------------------------------------
    # Stage 2: expand
    # ------------------------------------------------------------------
    t0 = time.perf_counter()
    expand_result = expand_stage.expand(working_text)
    latency_expand = (time.perf_counter() - t0) * 1000.0

    sink.record(
        EventRecord(
            task_id=task_id,
            kind="expand",
            tier=_DETERMINISTIC_TIER,
            tokens_exact=False,
            latency_ms=latency_expand,
        )
    )

    for note in expand_result.notes:
        lines.append(note)

    # ------------------------------------------------------------------
    # Stage 3: context
    # ------------------------------------------------------------------
    t0 = time.perf_counter()
    context_result = context_stage.gather(cwd)
    latency_context = (time.perf_counter() - t0) * 1000.0

    sink.record(
        EventRecord(
            task_id=task_id,
            kind="context",
            tier=_DETERMINISTIC_TIER,
            tokens_exact=False,
            latency_ms=latency_context,
        )
    )

    for ctx_line in context_result.lines:
        lines.append(ctx_line)

    # ------------------------------------------------------------------
    # Stage 3b: deslop — flag LLM "slop" phrasing in the working text.
    # SOFT (thesis #2): never rewrites the prompt, only annotates, so a false
    # positive costs one harmless line and nothing more.
    # ------------------------------------------------------------------
    t0 = time.perf_counter()
    slop_result = deslop_stage.find_slop(working_text)
    latency_deslop = (time.perf_counter() - t0) * 1000.0

    sink.record(
        EventRecord(
            task_id=task_id,
            kind="deslop",
            tier=_DETERMINISTIC_TIER,
            tokens_exact=False,
            latency_ms=latency_deslop,
        )
    )

    if not slop_result.clean:
        lines.append("slop flagged: " + ", ".join(slop_result.found))

    # ------------------------------------------------------------------
    # Stage 4: tag (the ONE fuzzy step — router is real; offloads to a local
    # model when model_tag is supplied, else deterministic keyword tags)
    # ------------------------------------------------------------------
    t0 = time.perf_counter()
    tag_result = tagmod.tag(working_text, manifest, model_tag=model_tag)
    latency_tag = (time.perf_counter() - t0) * 1000.0

    sink.record(
        EventRecord(
            task_id=task_id,
            kind="tag",
            tier=_tier_str(tag_result.tier),
            tokens_exact=False,
            latency_ms=latency_tag,
        )
    )

    if tag_result.tags:
        lines.append("tags: " + ", ".join(tag_result.tags))

    return Annotation.passthrough(lines)
