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


def test_tag_uses_model_tags_when_provided() -> None:
    def model_tag(tier: object, text: str) -> tuple[str, ...] | None:
        return ("refactor",)

    r = tagmod.tag(
        "anything at all",
        _m(local_models=(LocalModel("s", 4.0),)),
        model_tag=model_tag,
    )
    assert r.tags == ("refactor",)
    assert r.tier.is_model and r.tier.where == "local"


def test_tag_falls_soft_to_keywords_when_model_returns_none() -> None:
    def model_tag(tier: object, text: str) -> tuple[str, ...] | None:
        return None  # model declined / failed → SOFT fallback to keywords

    r = tagmod.tag(
        "please fix the error",
        _m(local_models=(LocalModel("s", 4.0),)),
        model_tag=model_tag,
    )
    assert "bug" in r.tags


def test_tag_skips_model_for_deterministic_tier() -> None:
    calls: list[object] = []

    def model_tag(tier: object, text: str) -> tuple[str, ...] | None:
        calls.append(tier)
        return ("refactor",)

    # No local models and no cloud → router yields the deterministic tier, so the
    # model tagger must NOT be invoked (no model to offload to).
    r = tagmod.tag(
        "fix bug",
        _m(gpu_vram_gb=None, cloud_available=False),
        model_tag=model_tag,
    )
    assert calls == []
    assert "bug" in r.tags


def test_pipeline_uses_model_tag_when_provided(tmp_path: Path) -> None:
    sink = MetricsSink(tmp_path / "e.jsonl")

    def model_tag(tier: object, text: str) -> tuple[str, ...] | None:
        return ("refactor",)

    ann = groom(
        "anything",
        manifest=_m(local_models=(LocalModel("s", 4.0),)),
        sink=sink,
        cwd=tmp_path,
        task_id="t",
        model_tag=model_tag,
    )
    assert any("refactor" in line for line in ann.lines)


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
    assert kinds == ["redact", "expand", "context", "recent_files", "entities", "clipboard", "deslop", "tag", "tool_select"]


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
