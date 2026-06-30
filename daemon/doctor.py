"""kx doctor reconciliation (self-healing, vision §9 #4).

A pure diagnosis of drift between what the manifest/registry expects and what the
runtime actually has:

  - ``missing_model``       — expected but not served (fixable: pull it).
  - ``orphan_model``        — served but not expected (fixable: register or drop).
  - ``checksum_drift``      — a protected file's hash changed (NOT auto-fixable; a
    protected-file change needs a human, hard truth #1).
  - ``backend_unreachable`` — a configured backend's endpoint did not answer the
    health probe (NOT auto-fixable; the broker fails SOFT and routes around it,
    but the operator should know a tier is dark). Harvested from
    ``cheatcodes/Agent-Reach`` (``agent_reach/doctor.py`` — per-channel
    ``check()`` health diagnostics with ordered fallback).

The CLI ``kx doctor --auto-fix`` consumes these findings and applies the fixable
ones; the impure I/O (pull, registry write, the actual socket/HTTP probe) lives
in that thin shell — :func:`diagnose_backends` takes the probe as a parameter so
it stays pure and offline-testable (the same injectable-probe pattern as
:func:`daemon.launch.up`).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
import subprocess

# A backend health probe: given a base URL, is it reachable? The real probe does
# I/O (an HTTP/socket round-trip); tests inject a pure stub.
BackendProbe = Callable[[str], bool]


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


def diagnose_backends(
    backends: dict[str, str],
    probe: BackendProbe,
) -> list[Finding]:
    """Return an ``backend_unreachable`` finding per backend that fails *probe*.

    *backends* maps a backend name (e.g. ``"ollama"``, ``"zai"``) to its base
    URL; *probe* answers "is this URL reachable?" (real probe does I/O, tests
    inject a stub). Findings are ``fixable=False``: the broker already fails SOFT
    and routes around a dark tier, so this is operator awareness, not an
    auto-fix — kinox never silently fabricates a "down" backend back up.
    """
    findings: list[Finding] = []
    for name in sorted(backends):
        if not probe(backends[name]):
            findings.append(
                Finding(
                    "backend_unreachable",
                    f"{name} ({backends[name]})",
                    fixable=False,
                )
            )
    return findings


def apply_fixes(findings: list[Finding]) -> None:
    """Attempt to automatically fix drift.
    
    Pulls missing models and removes orphaned models via the ollama CLI.
    """
    for finding in findings:
        if not finding.fixable:
            continue
            
        if finding.kind == "missing_model":
            print(f"  [auto-fix] pulling missing model: {finding.detail}...")
            subprocess.run(["ollama", "pull", finding.detail], check=False)
            
        elif finding.kind == "orphan_model":
            print(f"  [auto-fix] removing orphan model: {finding.detail}...")
            subprocess.run(["ollama", "rm", finding.detail], check=False)
