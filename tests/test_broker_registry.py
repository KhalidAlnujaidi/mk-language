"""Model registry with canary verification (M1 broker depth, vision §4.1).

Models declare capabilities; the broker verifies with a canary on registration
and quarantines liars. The canary is injected so tests run offline.
"""

from __future__ import annotations

from daemon.registry import ModelEntry, Registry


def _entry(name: str, **kw: object) -> ModelEntry:
    return ModelEntry(name=name, backend="ollama", **kw)  # type: ignore[arg-type]


def test_passing_canary_registers_as_candidate():
    reg = Registry()
    stored = reg.register(_entry("good"), canary=lambda e: True)
    assert stored.quarantined is False
    assert reg.get("good") is not None
    assert "good" in {e.name for e in reg.candidates()}


def test_failing_canary_quarantines_and_excludes_from_candidates():
    reg = Registry()
    entry = _entry("liar", capabilities=frozenset({"tools"}))
    stored = reg.register(entry, canary=lambda e: False)
    assert stored.quarantined is True
    assert "liar" not in {e.name for e in reg.candidates()}
    assert reg.get("liar") is not None  # still recorded, just quarantined


def test_canary_that_raises_is_treated_as_failure():
    reg = Registry()

    def boom(_e: ModelEntry) -> bool:
        raise RuntimeError("model never responded")

    stored = reg.register(_entry("broken"), canary=boom)
    assert stored.quarantined is True
    assert reg.candidates() == ()
