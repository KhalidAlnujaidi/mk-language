"""The architecture guardrail (vision §8.1) — exists from commit #1.

The kernel is pure, agent-agnostic, and dependency-light: it imports nothing
from the outer layers (`products/`, `adapters/`, `daemon/`). Enforcing this
mechanically keeps a future extraction of `kernel` into a versioned package a
purely mechanical step.

This walks the AST of every module under `kernel/` and fails if any of them
import a forbidden first-party top-level package.
"""

from __future__ import annotations

import ast
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
KERNEL = REPO_ROOT / "kernel"

# The kernel must not depend on the outer layers.
FORBIDDEN_TOPLEVEL = {"products", "adapters", "daemon"}


def _kernel_modules() -> list[Path]:
    return sorted(KERNEL.rglob("*.py"))


def _imported_toplevels(source: str, path: Path) -> set[str]:
    """Top-level package names imported by a module (absolute imports only)."""
    tree = ast.parse(source, filename=str(path))
    tops: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                tops.add(alias.name.split(".")[0])
        # node.level > 0 is a relative import → stays within kernel, allowed.
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            tops.add(node.module.split(".")[0])
    return tops


def test_kernel_imports_nothing_from_outer_layers() -> None:
    violations: list[str] = []
    for path in _kernel_modules():
        imported = _imported_toplevels(path.read_text(), path)
        for bad in sorted(imported & FORBIDDEN_TOPLEVEL):
            rel = path.relative_to(REPO_ROOT)
            violations.append(f"{rel} imports forbidden top-level package '{bad}'")
    assert not violations, "kernel purity violated:\n  " + "\n  ".join(violations)


def test_guardrail_actually_scans_files() -> None:
    # Sanity: if the kernel ever empties out, the test above passes vacuously.
    # This ensures the guardrail is pointed at real files.
    assert _kernel_modules(), "expected at least one module under kernel/"
