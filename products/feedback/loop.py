"""Next-turn feedback loop (vision §9 #1, thesis #3).

The user's immediate next-turn correction is the highest-value, free quality
label in the system. When the next prompt looks like a correction of the prior
turn (``kernel.corrections.looks_like_correction``), we write one
``EventRecord`` marked ``as_correction_of`` the prior task into the metrics
sink — so the correction link lives in the same honest observability stream as
everything else, ready for the reviewer (``products.feedback.review``) and the
§8.3 eval harness.

Note: richer structural capture (prior-output diff) is a documented follow-on;
the kernel ``EventRecord`` already carries the load-bearing ``correction_of``.
"""

from __future__ import annotations

from kernel.contracts import EventRecord
from kernel.corrections import looks_like_correction
from kernel.metrics import MetricsSink


def record_correction_if_any(
    sink: MetricsSink,
    *,
    prior_task_id: str,
    prior_prompt: str,
    next_prompt: str,
    task_id: str,
) -> bool:
    """If *next_prompt* corrects the prior turn, record the link and return True.

    Writes a single ``EventRecord`` (kind ``"correction"``) marked as correcting
    ``prior_task_id``. Returns ``False`` and writes nothing otherwise.
    """
    if not looks_like_correction(prior_prompt, next_prompt):
        return False
    event = EventRecord(
        task_id=task_id, kind="correction", tier="deterministic"
    ).as_correction_of(prior_task_id)
    sink.record(event)
    return True
