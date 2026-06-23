"""kx doctor reconciliation (self-healing, vision §9 #4).

Pure diagnosis of manifest/registry-vs-runtime drift: models expected but not
served, models served but not expected, and protected-file checksum drift.
auto-fixability is per-finding (a checksum drift on a protected file is NOT
auto-fixable — it needs a human).
"""

from __future__ import annotations

from daemon.doctor import diagnose


def test_missing_model_is_flagged_fixable():
    findings = diagnose(expected_models={"a", "b"}, present_models={"a"})
    missing = [f for f in findings if f.kind == "missing_model"]
    assert len(missing) == 1
    assert missing[0].detail == "b"
    assert missing[0].fixable is True  # can pull it


def test_orphan_runtime_model_is_flagged():
    findings = diagnose(expected_models={"a"}, present_models={"a", "ghost"})
    assert any(f.kind == "orphan_model" and f.detail == "ghost" for f in findings)


def test_checksum_drift_is_flagged_not_autofixable():
    findings = diagnose(
        expected_models=set(),
        present_models=set(),
        checksums_expected={"alignment/CONSTITUTION.md": "abc"},
        checksums_actual={"alignment/CONSTITUTION.md": "xyz"},
    )
    drift = [f for f in findings if f.kind == "checksum_drift"]
    assert len(drift) == 1
    assert drift[0].fixable is False  # protected file changed → human only


def test_clean_system_has_no_findings():
    assert diagnose(expected_models={"a"}, present_models={"a"}) == []
