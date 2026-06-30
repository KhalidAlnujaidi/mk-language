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

import concurrent.futures
import time
from pathlib import Path
from typing import Callable, Any

from kernel.contracts import Annotation, EventRecord, Tier
from kernel.manifest import Manifest
from kernel.metrics import MetricsSink
from kernel.tracing import span

from products.groom import tag as tagmod
from products.groom.stages import context as context_stage
from products.groom.stages import recent_files as recent_files_stage
from products.groom.stages import deslop as deslop_stage
from products.groom.stages import entities as entities_stage
from products.groom.stages import expand as expand_stage
from products.groom.stages import redact as redact_stage
from products.groom.stages import tool_selector as tool_selector_stage
from products.groom.stages import clipboard as clipboard_stage
from products.groom.tag import ModelTag

_DETERMINISTIC_TIER: str = "deterministic"


def _tier_str(tier: Tier) -> str:
    """Convert a ``Tier`` to the canonical EventRecord tier string."""
    if not tier.is_model:
        return _DETERMINISTIC_TIER
    return f"model:{tier.where}"


def _time_it(func: Callable[..., Any], *args: Any, **kwargs: Any) -> tuple[Any, float]:
    """Run a function and return (result, latency_ms)."""
    t0 = time.perf_counter()
    res = func(*args, **kwargs)
    return res, (time.perf_counter() - t0) * 1000.0


def groom(
    prompt: str,
    *,
    manifest: Manifest,
    sink: MetricsSink,
    cwd: Path,
    task_id: str,
    model_tag: ModelTag | None = None,
    model_select: tool_selector_stage.ModelSelect | None = None,
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
    # The "groom" span of the end-to-end trace (vision §7): wraps the whole
    # pipeline. Per-stage latency is already in the JSONL EventRecords; a no-op
    # unless a tracer is installed.
    with span("groom", {"kinox.task_id": task_id}):
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
        # Stages 2, 3, 3b, 4: executed concurrently
        # ------------------------------------------------------------------
        with concurrent.futures.ThreadPoolExecutor(max_workers=6) as executor:
            fut_expand = executor.submit(
                _time_it, expand_stage.expand, working_text, cwd=cwd
            )
            fut_context = executor.submit(_time_it, context_stage.gather, cwd)
            fut_recent = executor.submit(_time_it, recent_files_stage.gather, cwd)
            fut_entities = executor.submit(
                _time_it, entities_stage.extract_entities, working_text, cwd=cwd
            )
            fut_clipboard = executor.submit(
                _time_it, clipboard_stage.get_clipboard, working_text
            )
            fut_deslop = executor.submit(
                _time_it, deslop_stage.find_slop, working_text
            )
            fut_tag = executor.submit(
                _time_it, tagmod.tag, working_text, manifest, model_tag=model_tag
            )
            fut_select = executor.submit(
                _time_it, tool_selector_stage.select, working_text, manifest, model_select=model_select
            )

            expand_result, latency_expand = fut_expand.result()
            context_result, latency_context = fut_context.result()
            recent_result, latency_recent = fut_recent.result()
            entities_result, latency_entities = fut_entities.result()
            clipboard_result, latency_clipboard = fut_clipboard.result()
            slop_result, latency_deslop = fut_deslop.result()
            tag_result, latency_tag = fut_tag.result()
            select_result, latency_select = fut_select.result()

        # Sequentially record the metrics and output annotations
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

        sink.record(
            EventRecord(
                task_id=task_id,
                kind="recent_files",
                tier=_DETERMINISTIC_TIER,
                tokens_exact=False,
                latency_ms=latency_recent,
            )
        )
        for r_line in recent_result.lines:
            lines.append(r_line)

        sink.record(
            EventRecord(
                task_id=task_id,
                kind="entities",
                tier=_DETERMINISTIC_TIER,
                tokens_exact=False,
                latency_ms=latency_entities,
            )
        )
        if not entities_result.clean:
            for entity in entities_result.found:
                lines.append(f"entity: {entity}")

        sink.record(
            EventRecord(
                task_id=task_id,
                kind="clipboard",
                tier=_DETERMINISTIC_TIER,
                tokens_exact=False,
                latency_ms=latency_clipboard,
            )
        )
        if clipboard_result.content:
            lines.append("clipboard content:\n" + clipboard_result.content)

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

        sink.record(
            EventRecord(
                task_id=task_id,
                kind="tool_select",
                tier=_tier_str(select_result.tier),
                tokens_exact=False,
                latency_ms=latency_select,
            )
        )
        if select_result.tools:
            lines.append("tools restricted to: " + ", ".join(select_result.tools))

        return Annotation.passthrough(lines)
