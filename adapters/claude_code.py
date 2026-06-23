"""adapters/claude_code.py — the only Claude-specific file.

Wires the kinox groom pipeline to the Claude Code ``UserPromptSubmit`` hook.

Thesis #3 (honest append-only correction): when the user's immediate next
prompt looks like a correction, we mark the most recent ``tag`` event as
``correction_of`` the prior tag event's ``task_id`` by appending a NEW boundary
record — never rewriting history.

Fail-soft discipline: any parse error in ``main`` → print nothing, return 0.
The hook must never block the user because the adapter choked.
"""

from __future__ import annotations

import dataclasses
import json
import sys
import uuid
from dataclasses import dataclass
from pathlib import Path

from kernel.contracts import Annotation, EventRecord
from kernel.corrections import looks_like_correction
from kernel.manifest import probe
from kernel.metrics import MetricsSink
from products.groom.model_tag import broker_tag
from products.groom.pipeline import groom
from products.groom.tag import ModelTag

# ---------------------------------------------------------------------------
# State paths
# ---------------------------------------------------------------------------

STATE_DIR: Path = Path.home() / ".kinox"
EVENTS_PATH: Path = STATE_DIR / "events.jsonl"
LAST_PROMPT_PATH: Path = STATE_DIR / "last_prompt.txt"

# ---------------------------------------------------------------------------
# Result type
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class AdapterResult:
    """What ``handle`` returns — the annotation and whether this was a correction."""

    annotation: Annotation
    was_correction: bool


# ---------------------------------------------------------------------------
# Core handler
# ---------------------------------------------------------------------------


def handle(
    hook_input: dict[str, object],
    *,
    cwd: Path,
    sink: MetricsSink,
    last_prompt: str | None,
    model_tag: ModelTag | None = None,
) -> AdapterResult:
    """Process one ``UserPromptSubmit`` hook payload.

    Extracts the prompt, runs the groom pipeline, and — if this looks like a
    correction — appends a new ``tag`` boundary record linking it to the prior
    tag's ``task_id``.

    Parameters
    ----------
    hook_input:
        The raw JSON payload from Claude Code's ``UserPromptSubmit`` hook.
        Must contain a ``"prompt"`` key.
    cwd:
        Working directory for the context stage (git/fs probes).
    sink:
        The ``MetricsSink`` to record events into.
    last_prompt:
        The prompt from the immediately preceding turn, or ``None`` if there
        was no prior turn.
    model_tag:
        Optional broker-backed tagger for the fuzzy tag step (offload to a local
        model). ``None`` keeps the deterministic keyword tagging (tests inject
        ``None``; the live ``main`` injects ``broker_tag()``).

    Returns
    -------
    AdapterResult
        The groomed ``Annotation`` and a ``was_correction`` flag.
    """
    prompt = str(hook_input["prompt"])

    # Determine correction before running groom so we can capture the prior
    # tag event index (everything in sink so far) vs the new tag event.
    is_correction = (
        last_prompt is not None and looks_like_correction(last_prompt, prompt)
    )

    # Capture index of last event before this groom call so we can find the
    # prior tag and the new tag by position.
    events_before = sink.read_all()
    prior_tag: EventRecord | None = None
    if is_correction:
        # Most recent tag event before this call.
        for ev in reversed(events_before):
            if ev.kind == "tag":
                prior_tag = ev
                break

    manifest = probe()
    task_id = str(uuid.uuid4())
    annotation = groom(
        prompt,
        manifest=manifest,
        sink=sink,
        cwd=cwd,
        task_id=task_id,
        model_tag=model_tag,
    )

    was_correction = False
    if is_correction and prior_tag is not None:
        # Find the tag event just recorded (most recent tag in sink now).
        all_events = sink.read_all()
        current_tag: EventRecord | None = None
        for ev in reversed(all_events):
            if ev.kind == "tag":
                current_tag = ev
                break

        if current_tag is not None:
            # Append a new correction boundary record — never mutate history.
            # The correction record must have its OWN unique task_id so that no
            # two records in the event log share an id.
            correction_record = dataclasses.replace(
                current_tag,
                task_id=str(uuid.uuid4()),
                correction_of=prior_tag.task_id,
            )
            sink.record(correction_record)
            was_correction = True

    return AdapterResult(annotation=annotation, was_correction=was_correction)


# ---------------------------------------------------------------------------
# CLI entry point (stdin JSON → stdout annotation lines)
# ---------------------------------------------------------------------------


def main(stdin_text: str) -> int:
    """Parse the Claude Code hook JSON from *stdin_text* and run the adapter.

    Fail-soft: any exception → print nothing, return 0 (never block the user).
    """
    try:
        hook_input: dict[str, object] = json.loads(stdin_text)

        last_prompt: str | None = None
        if LAST_PROMPT_PATH.exists():
            raw = LAST_PROMPT_PATH.read_text(encoding="utf-8").strip()
            if raw:
                last_prompt = raw

        sink = MetricsSink(EVENTS_PATH)
        cwd = Path.cwd()

        # Live path offloads the fuzzy tag step to a local model via the broker;
        # broker_tag fails soft to keyword tags if no backend answers.
        result = handle(
            hook_input,
            cwd=cwd,
            sink=sink,
            last_prompt=last_prompt,
            model_tag=broker_tag(),
        )

        # Persist the current prompt for the next turn.
        prompt = str(hook_input["prompt"])
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        LAST_PROMPT_PATH.write_text(prompt, encoding="utf-8")

        # Emit annotation lines as additive hook context.
        for line in result.annotation.lines:
            print(line)

    except Exception:
        # Fail soft — never block the user because the adapter choked.
        return 0

    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.stdin.read()))
