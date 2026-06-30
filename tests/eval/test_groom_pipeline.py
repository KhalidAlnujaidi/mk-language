# swarm-drafted (node=gemma-agent-7, model=Nemotron-14B); curated locally
# Behavioral: grooming a secret-bearing prompt records exactly one EventRecord
# per stage (5) and surfaces a redaction line. (Fixed: the draft used probe(cwd)
# [probe() takes no arg], a `.event`-file check [the sink is one JSONL file], a
# leaked non-ASCII token, and a prompt with no actual secret.)
import tempfile
from pathlib import Path

from kernel.manifest import probe
from kernel.metrics import MetricsSink
from products.groom.pipeline import groom


def test_groom_records_one_event_per_stage_and_redacts():
    cwd = Path(tempfile.mkdtemp())
    sink_path = Path(tempfile.mkdtemp()) / "metrics.jsonl"
    sink = MetricsSink(sink_path)

    prompt = "deploy with key AKIAIOSFODNN7EXAMPLE please"
    annotation = groom(prompt, manifest=probe(), sink=sink, cwd=cwd, task_id="t-groom")

    # one EventRecord per stage: redact, expand, context, recent_files, entities, clipboard, deslop, tag, tool_select
    assert len(sink.read_all()) == 9

    # the redaction is surfaced as an additive context line
    assert any("redacted" in line.lower() for line in annotation.lines)
