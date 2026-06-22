"""Stage: redact — deterministic secret detection and replacement.

Thesis #1: ground truth beats the model — pure regex, no model call.
Thesis #2: fail-direction is CLOSED (guard semantics).
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from kernel.contracts import FailDirection

FAIL_DIRECTION: FailDirection = FailDirection.CLOSED

# Compile patterns once at module level.
_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("anthropic_key", re.compile(r"sk-ant-[A-Za-z0-9_-]{20,}")),
    ("openai_key", re.compile(r"sk-[A-Za-z0-9]{20,}")),
    ("aws_key", re.compile(r"AKIA[0-9A-Z]{16}")),
    ("generic_hex_token", re.compile(r"\b[0-9a-fA-F]{32,}\b")),
)


@dataclass(frozen=True)
class RedactResult:
    """The result of a redaction pass."""

    text: str
    found: tuple[str, ...]


def redact(text: str) -> RedactResult:
    """Replace every detected secret with ``«REDACTED:{kind}»``.

    Patterns are applied in order; each pass redacts on the cumulative result
    so that an earlier redaction cannot mask a later pattern.
    """
    result = text
    found: list[str] = []
    for kind, pattern in _PATTERNS:
        replaced, n = pattern.subn(f"«REDACTED:{kind}»", result)
        if n > 0:
            found.append(kind)
            result = replaced
    return RedactResult(text=result, found=tuple(found))
