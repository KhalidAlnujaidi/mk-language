"""kx doctor reconciliation (self-healing, vision §9 #4).

A pure diagnosis of drift between what the manifest/registry expects and what the
runtime actually has:

  - ``missing_model``  — expected but not served (fixable: pull it).
  - ``orphan_model``   — served but not expected (fixable: register or drop).
  - ``checksum_drift`` — a protected file's hash changed (NOT auto-fixable; a
    protected-file change needs a human, hard truth #1).

The CLI ``kx doctor --auto-fix`` consumes these findings and applies the fixable
ones; the impure I/O (pull, registry write) lives in that thin shell.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Finding:
    """One reconciliation finding. ``fixable`` gates ``--auto-fix``."""

    kind: str
    detail: str
    fixable: bool


def diagnose(
    *,
    expected_models: set[str],
    present_models: set[str],
    checksums_expected: dict[str, str] | None = None,
    checksums_actual: dict[str, str] | None = None,
) -> list[Finding]:
    """Return all drift findings between expected and runtime state."""
    findings: list[Finding] = []

    for name in sorted(expected_models - present_models):
        findings.append(Finding("missing_model", name, fixable=True))
    for name in sorted(present_models - expected_models):
        findings.append(Finding("orphan_model", name, fixable=True))

    expected_sums = checksums_expected or {}
    actual_sums = checksums_actual or {}
    for path in sorted(expected_sums):
        if path in actual_sums and actual_sums[path] != expected_sums[path]:
            findings.append(Finding("checksum_drift", path, fixable=False))

    return findings
