"""Regression runner for the golden eval set (vision §8.3).

Runs a pytest test directory and returns a structured verdict, so any proposed
change can be gated on "did the behavioral eval set still pass?". Reuses pytest
as the engine (Rule Zero) via a subprocess, so running it from inside pytest
does not nest interpreters.

Counts come from pytest's ``--junit-xml`` report (parsed with stdlib
ElementTree), not the console summary line — the summary text varies with a
project's pytest config (``addopts``), whereas the XML tallies are stable.
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from dataclasses import dataclass


@dataclass(frozen=True)
class EvalReport:
    """Outcome of one eval-set run. ``ok`` needs >=1 test and zero failures."""

    total: int
    passed: int
    failed: int

    @property
    def ok(self) -> bool:
        return self.total > 0 and self.failed == 0


def run_eval_set(path: str = "tests/eval") -> EvalReport:
    """Run the pytest suite at *path* and summarise pass/fail counts."""
    with tempfile.TemporaryDirectory() as tmp:
        report_xml = os.path.join(tmp, "report.xml")
        subprocess.run(
            [
                sys.executable, "-m", "pytest", path,
                "-q", "--tb=no", "-p", "no:cacheprovider",
                f"--junit-xml={report_xml}",
            ],
            capture_output=True,
            text=True,
        )
        # Safe to use stdlib ET: report_xml is produced by our own pytest run
        # into a temp dir we control and discard — never untrusted input, so the
        # XXE / entity-expansion attack surface does not apply here.
        root = ET.parse(report_xml).getroot()

    # <testsuites> wraps one-or-more <testsuite>; sum tallies across all.
    suites = root.findall("testsuite") if root.tag == "testsuites" else [root]
    total = failed = skipped = 0
    for s in suites:
        total += int(s.get("tests", 0))
        failed += int(s.get("failures", 0)) + int(s.get("errors", 0))
        skipped += int(s.get("skipped", 0))
    return EvalReport(total=total, passed=total - failed - skipped, failed=failed)
