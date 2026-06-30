# golden eval — expand stage (products/groom/stages/expand.py)
# Behavioral: @-path mentions get an existence note (ground-truth fs lookup);
# email addresses are NOT treated as path mentions; the stage is SOFT.
from pathlib import Path

from products.groom.stages.expand import expand


def test_expand_notes_existing_path(tmp_path: Path):
    f = tmp_path / "real.txt"
    f.write_text("x")
    result = expand(f"please read @{f} now")
    assert result.text == f"please read @{f} now"  # text unchanged (additive notes)
    assert any("exists" in note for note in result.notes)


def test_expand_notes_missing_path(tmp_path: Path):
    missing = tmp_path / "nope.txt"
    result = expand(f"open @{missing}")
    assert any("missing" in note for note in result.notes)


def test_expand_ignores_email_address():
    result = expand("ping me at user@example.com")
    assert result.notes == ()  # email is not a path mention
