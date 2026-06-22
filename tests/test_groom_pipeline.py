"""Tests for products/groom/tag.py and products/groom/pipeline.py."""

from __future__ import annotations

from pathlib import Path

from kernel.manifest import LocalModel, Manifest
from kernel.metrics import MetricsSink
from products.groom import tag as tagmod
from products.groom.pipeline import groom


def _m(**kw: object) -> Manifest:
    base: dict[str, object] = dict(
        cpu_count=8,
        ram_gb=60.0,
        gpu_vram_gb=20.0,
        local_models=(),
        cloud_available=False,
    )
    base.update(kw)
    return Manifest(**base)  # type: ignore[arg-type]


def test_tag_emits_keyword_tags_and_a_tier() -> None:
    r = tagmod.tag(
        "please fix the error in login", _m(local_models=(LocalModel("s", 4.0),))
    )
    assert "bug" in r.tags
    assert r.tier.is_model and r.tier.where == "local"


def test_pipeline_redacts_and_records_an_event_per_stage(tmp_path: Path) -> None:
    sink = MetricsSink(tmp_path / "e.jsonl")
    ann = groom(
        "add login; key sk-ant-api03-AAAAAAAAAAAAAAAAAAAAAAAA",
        manifest=_m(),
        sink=sink,
        cwd=tmp_path,
        task_id="t1",
    )
    assert ann.is_blocked is False
    assert any("redacted" in line for line in ann.lines)
    kinds = [e.kind for e in sink.read_all()]
    assert kinds == ["redact", "expand", "context", "tag"]


def test_pipeline_tags_appear_in_annotation(tmp_path: Path) -> None:
    sink = MetricsSink(tmp_path / "e.jsonl")
    ann = groom(
        "implement a new feature", manifest=_m(), sink=sink, cwd=tmp_path, task_id="t2"
    )
    assert any("feature" in line for line in ann.lines)


def test_pipeline_tag_event_records_routed_tier(tmp_path: Path) -> None:
    sink = MetricsSink(tmp_path / "e.jsonl")
    groom(
        "fix bug",
        manifest=_m(cloud_available=True, gpu_vram_gb=None),
        sink=sink,
        cwd=tmp_path,
        task_id="t3",
    )
    tag_ev = [e for e in sink.read_all() if e.kind == "tag"][0]
    assert tag_ev.tier == "model:cloud"
