"""Dev-role guard — a PreToolUse hook that keeps a `developer` session in bounds.

No-op unless ``KINOX_ROLE=developer``. For a developer it DENIES file-editing
tools (Write / Edit / MultiEdit / NotebookEdit) whose target is *framework code*
— anything under the kinox repo but outside ``projects/``. It is a guardrail
with teeth (a collaborator can't silently rewrite the kernel), not an airtight
sandbox: it covers the edit tools, not arbitrary Bash. Allow = no output; deny =
a PreToolUse deny decision (JSON). Always exits 0 (decisions ride the JSON, not
the exit code), and fails OPEN on unparseable input (never wedge the user).
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import cast

EDIT_TOOLS = {"Write", "Edit", "MultiEdit", "NotebookEdit"}


def decide(payload: dict[str, object], *, repo_root: Path) -> tuple[str, str]:
    """Return ("allow"|"deny", reason). Pure — no env, no I/O, no stdin."""
    if payload.get("tool_name") not in EDIT_TOOLS:
        return "allow", ""
    tool_input = payload.get("tool_input")
    if not isinstance(tool_input, dict):
        return "allow", ""
    ti = cast("dict[str, object]", tool_input)
    raw = ti.get("file_path") or ti.get("notebook_path")
    if not isinstance(raw, str) or not raw:
        return "allow", ""

    repo = repo_root.resolve()
    projects = (repo / "projects").resolve()
    target = Path(raw)
    if not target.is_absolute():
        target = repo / target
    target = target.resolve()

    inside_repo = target == repo or repo in target.parents
    inside_projects = target == projects or projects in target.parents
    if inside_repo and not inside_projects:
        return "deny", (
            f"[{Path(__file__).name}:46] developer role: '{target}' is framework code (outside projects/). "
            "Work within your project; ask an admin for kernel/framework changes."
        )
    return "allow", ""


def main(stdin_text: str) -> int:
    if os.environ.get("KINOX_ROLE") != "developer":
        return 0  # no-op for admin / unscoped sessions (microsecond fast-path)
    try:
        payload = json.loads(stdin_text)
    except Exception:
        return 0  # fail open — never block on garbage
    if not isinstance(payload, dict):
        return 0
    repo_root = Path(__file__).resolve().parents[1]
    decision, reason = decide(cast("dict[str, object]", payload), repo_root=repo_root)
    if decision == "deny":
        print(
            json.dumps(
                {
                    "hookSpecificOutput": {
                        "hookEventName": "PreToolUse",
                        "permissionDecision": "deny",
                        "permissionDecisionReason": reason,
                    }
                }
            )
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.stdin.read()))
