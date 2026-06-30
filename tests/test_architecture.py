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
DAEMON = REPO_ROOT / "daemon"

# The kernel must not depend on the outer layers.
FORBIDDEN_TOPLEVEL = {"products", "adapters", "daemon"}

# The daemon (broker, M1) is an outer layer: it may consume the kernel but must
# not reach sideways into the other product/adapter layers.
DAEMON_FORBIDDEN_TOPLEVEL = {"products", "adapters"}


def _kernel_modules() -> list[Path]:
    return sorted(p for p in KERNEL.rglob("*.py") if not p.name.startswith("._"))


def _daemon_modules() -> list[Path]:
    return sorted(p for p in DAEMON.rglob("*.py") if not p.name.startswith("._"))


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


def test_daemon_does_not_import_other_product_layers() -> None:
    # The broker daemon may import kernel/, but never products/ or adapters/.
    violations: list[str] = []
    for path in _daemon_modules():
        imported = _imported_toplevels(path.read_text(), path)
        for bad in sorted(imported & DAEMON_FORBIDDEN_TOPLEVEL):
            rel = path.relative_to(REPO_ROOT)
            violations.append(f"{rel} imports forbidden top-level package '{bad}'")
    assert not violations, "daemon layering violated:\n  " + "\n  ".join(violations)


def test_daemon_may_import_kernel() -> None:
    # The broker is a real consumer of the kernel contracts; prove the allowed
    # direction is actually exercised (and so the reverse-import ban is meaningful).
    kernel_consumers = [
        path
        for path in _daemon_modules()
        if "kernel" in _imported_toplevels(path.read_text(), path)
    ]
    assert kernel_consumers, "expected daemon/ to import kernel/ (consumes contracts)"
