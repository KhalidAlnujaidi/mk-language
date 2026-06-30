"""Stage: clipboard — pbpaste injection.

Thesis #1: ground truth beats the model — pure pbpaste execution.
Thesis #2: fail-direction is SOFT; degrades to empty Result on error.
"""

from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass

from kernel.contracts import FailDirection

FAIL_DIRECTION: FailDirection = FailDirection.SOFT

_CLIPBOARD_MENTION = re.compile(r"(?:^|\s)(?:@clipboard|%pbpaste)\b", flags=re.IGNORECASE)


@dataclass(frozen=True)
class ClipboardResult:
    """The result of the clipboard scan."""
    content: str | None


def get_clipboard(text: str) -> ClipboardResult:
    """Scan *text* for @clipboard or %pbpaste. If found, run pbpaste."""
    if not _CLIPBOARD_MENTION.search(text):
        return ClipboardResult(content=None)

    try:
        out = subprocess.run(
            ["pbpaste"], capture_output=True, text=True, timeout=2
        )
        if out.returncode == 0 and out.stdout:
            lines = out.stdout.splitlines()
            if len(lines) > 500:
                snippet = "\n".join(lines[:500])
                return ClipboardResult(content=f"```\n{snippet}\n```\n... (truncated {len(lines) - 500} lines)")
            else:
                snippet = "\n".join(lines)
                return ClipboardResult(content=f"```\n{snippet}\n```")
    except Exception:
        pass

    return ClipboardResult(content=None)
