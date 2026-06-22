"""Regression runner for the golden eval set (vision §8.3).

Runs a pytest test directory and returns a structured verdict, so any proposed
change can be gated on "did the behavioral eval set still pass?". Reuses pytest
as the engine (Rule Zero) via a subprocess, so running it from inside pytest
does not nest interpreters.
"""

from __future__ import annotations

import re
import subprocess
import sys
from dataclasses import dataclass

# pytest summary fragments, e.g. "1 passed", "2 failed", "1 error".
_SUMMARY = re.compile(r"(\d+) (passed|failed|error)")


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
    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            path,
            "-q",
            "--tb=no",
            "-p",
            "no:cacheprovider",
        ],
        capture_output=True,
        text=True,
    )
    passed = failed = 0
    for n, kind in _SUMMARY.findall(proc.stdout):
        if kind == "passed":
            passed += int(n)
        else:  # failed or error
            failed += int(n)
    return EvalReport(total=passed + failed, passed=passed, failed=failed)
