"""Tests for products/groom/ingest.py — markitdown document ingest.

The converter is injectable, so the success path is tested with a pure stub and
the SOFT failure paths need no markitdown install and no real files.
"""

from __future__ import annotations

from pathlib import Path

from kernel.contracts import FailDirection
from products.groom import ingest as ingest_mod
from products.groom.ingest import ingest


def test_missing_file_fails_soft(tmp_path: Path) -> None:
    r = ingest(tmp_path / "nope.pdf")
    assert r.ok is False
    assert r.markdown == ""
    assert "no such file" in r.note


def test_successful_conversion_with_injected_converter(tmp_path: Path) -> None:
    doc = tmp_path / "doc.docx"
    doc.write_text("binary-ish")
    r = ingest(doc, converter=lambda p: f"# Heading\n\nfrom {p.name}")
    assert r.ok is True
    assert r.markdown.startswith("# Heading")
    assert r.note == ""


def test_missing_markitdown_is_reported_softly(tmp_path: Path) -> None:
    doc = tmp_path / "doc.pdf"
    doc.write_text("x")

    def raise_import(_: Path) -> str:
        raise ImportError("no markitdown")

    r = ingest(doc, converter=raise_import)
    assert r.ok is False
    assert "markitdown not installed" in r.note


def test_conversion_error_degrades_to_no_doc(tmp_path: Path) -> None:
    doc = tmp_path / "doc.pptx"
    doc.write_text("x")

    def boom(_: Path) -> str:
        raise ValueError("corrupt")

    r = ingest(doc, converter=boom)
    assert r.ok is False
    assert r.markdown == ""
    assert "ValueError" in r.note


def test_fail_direction_is_soft() -> None:
    assert ingest_mod.FAIL_DIRECTION is FailDirection.SOFT
