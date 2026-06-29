#!/usr/bin/env python3
"""Tests for the 5 new v3 distillation router template handlers.

Tests the extractors and generators for:
  - tail-lines
  - reverse-lines
  - unique-lines
  - transform-case
  - replace-text
"""
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from distill_router import (
    _extract_filename_and_count_last,
    _extract_transform_case,
    _extract_replace_pairs,
    _extract_filename,
    _gen_tail_lines,
    _gen_reverse_lines,
    _gen_unique_lines,
    _gen_transform_case,
    _gen_replace_text,
    TEMPLATE_HANDLERS,
)


# ---------------------------------------------------------------------------
# Extractor tests
# ---------------------------------------------------------------------------

def test_extract_tail_count_basic():
    result = _extract_filename_and_count_last("get the last 3 lines of alpha.txt")
    assert result == ("alpha.txt", 3), f"Expected ('alpha.txt', 3), got {result}"

def test_extract_tail_count_missing_lines_word():
    result = _extract_filename_and_count_last("show last 2 of alpha.txt")
    assert result is not None, "Should extract count even without 'lines'"
    assert result[0] == "alpha.txt"
    assert result[1] == 2

def test_extract_tail_count_bottom():
    result = _extract_filename_and_count_last("bottom 2 lines from alpha.txt")
    assert result is not None
    assert result[0] == "alpha.txt"

def test_extract_transform_upper():
    result = _extract_transform_case("convert alpha.txt to uppercase")
    assert result == ("upper", "alpha.txt"), f"Got {result}"

def test_extract_transform_lower():
    result = _extract_transform_case("change alpha.txt to lowercase")
    assert result == ("lower", "alpha.txt"), f"Got {result}"

def test_extract_transform_caps():
    result = _extract_transform_case("make alpha.txt all caps")
    assert result == ("upper", "alpha.txt"), f"Got {result}"

def test_extract_transform_no_direction():
    result = _extract_transform_case("read alpha.txt")
    assert result is None

def test_extract_replace_quoted():
    result = _extract_replace_pairs('replace "old" with "new" in alpha.txt')
    assert result == ("old", "new", "alpha.txt"), f"Got {result}"

def test_extract_replace_swap():
    result = _extract_replace_pairs('swap "cat" with "dog" in alpha.txt')
    assert result == ("cat", "dog", "alpha.txt"), f"Got {result}"

def test_extract_replace_substitute():
    result = _extract_replace_pairs('substitute "x" by "y" in alpha.txt')
    assert result is not None
    assert result[0] == "x"
    assert result[1] == "y"
    assert result[2] == "alpha.txt"


# ---------------------------------------------------------------------------
# Generator tests
# ---------------------------------------------------------------------------

def test_gen_tail_lines():
    result = _gen_tail_lines(("alpha.txt", 3))
    assert result == ["show last 3 lines of alpha.txt"]

def test_gen_reverse_lines():
    result = _gen_reverse_lines("alpha.txt")
    assert result == ["reverse lines in alpha.txt"]

def test_gen_unique_lines():
    result = _gen_unique_lines("alpha.txt")
    assert result == ["unique lines in alpha.txt"]

def test_gen_transform_upper():
    result = _gen_transform_case(("upper", "alpha.txt"))
    assert result == ["uppercase alpha.txt"]

def test_gen_transform_lower():
    result = _gen_transform_case(("lower", "alpha.txt"))
    assert result == ["lowercase alpha.txt"]

def test_gen_replace_text():
    result = _gen_replace_text(("old", "new", "alpha.txt"))
    assert result == ['replace "old" with "new" in alpha.txt']


# ---------------------------------------------------------------------------
# Template handler registration tests
# ---------------------------------------------------------------------------

def test_handlers_registered():
    """All 5 new template types are in TEMPLATE_HANDLERS."""
    for name in ['tail-lines', 'reverse-lines', 'unique-lines', 'transform-case', 'replace-text']:
        assert name in TEMPLATE_HANDLERS, f"Missing handler for {name}"

def test_total_handler_count():
    """Should have 14 handlers total (9 original + 5 new)."""
    assert len(TEMPLATE_HANDLERS) == 14, f"Expected 14, got {len(TEMPLATE_HANDLERS)}"


# ---------------------------------------------------------------------------
# End-to-end generation tests (extract + generate → parseable NL)
# ---------------------------------------------------------------------------

def test_e2e_tail_lines():
    """Extract params from conversational request and generate parseable NL."""
    params = _extract_filename_and_count_last("get the last 2 lines of data.txt")
    steps = _gen_tail_lines(params)
    # The generated step should be parseable by the ASG
    from asg import parse
    nodes = parse("\n".join(steps))
    assert any(type(n).__name__ == "TailLines" for n in nodes), \
        f"Expected TailLines node, got {[type(n).__name__ for n in nodes]}"

def test_e2e_reverse_lines():
    params = _extract_filename("reverse the lines in data.txt")
    steps = _gen_reverse_lines(params)
    from asg import parse
    nodes = parse("\n".join(steps))
    assert any(type(n).__name__ == "ReverseLines" for n in nodes)

def test_e2e_unique_lines():
    params = _extract_filename("unique lines in data.txt")
    steps = _gen_unique_lines(params)
    from asg import parse
    nodes = parse("\n".join(steps))
    assert any(type(n).__name__ == "UniqueLines" for n in nodes)

def test_e2e_transform_case():
    params = _extract_transform_case("uppercase data.txt")
    steps = _gen_transform_case(params)
    from asg import parse
    nodes = parse("\n".join(steps))
    assert any(type(n).__name__ == "TransformCase" for n in nodes)

def test_e2e_replace_text():
    params = _extract_replace_pairs('replace "foo" with "bar" in data.txt')
    steps = _gen_replace_text(params)
    from asg import parse
    nodes = parse("\n".join(steps))
    assert any(type(n).__name__ == "ReplaceText" for n in nodes)


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    passed = 0
    failed = 0
    for test in tests:
        try:
            test()
            print(f"  ✅ {test.__name__}")
            passed += 1
        except Exception as e:
            print(f"  ❌ {test.__name__}: {e}")
            failed += 1
    print(f"\n{'='*50}")
    print(f"  {passed}/{passed+failed} passed ({failed} failed)")
    if failed:
        sys.exit(1)
