"""kx doctor reconciliation (self-healing, vision §9 #4).

Pure diagnosis of manifest/registry-vs-runtime drift: models expected but not
served, models served but not expected, and protected-file checksum drift.
auto-fixability is per-finding (a checksum drift on a protected file is NOT
auto-fixable — it needs a human).
"""

from __future__ import annotations

from daemon.doctor import diagnose, diagnose_backends


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


# --- backend reachability (Agent-Reach harvest) ----------------------------


def test_unreachable_backend_is_flagged_not_autofixable():
    backends = {"ollama": "http://localhost:11434", "zai": "https://api.z.ai"}
    findings = diagnose_backends(backends, probe=lambda url: "z.ai" in url)
    assert len(findings) == 1
    f = findings[0]
    assert f.kind == "backend_unreachable"
    assert f.detail.startswith("ollama")
    assert f.fixable is False  # broker fails SOFT; operator awareness only


def test_all_backends_reachable_has_no_findings():
    backends = {"ollama": "http://localhost:11434"}
    assert diagnose_backends(backends, probe=lambda _: True) == []


def test_findings_are_sorted_by_backend_name():
    backends = {"zeta": "u1", "alpha": "u2"}
    findings = diagnose_backends(backends, probe=lambda _: False)
    assert [f.detail.split()[0] for f in findings] == ["alpha", "zeta"]
