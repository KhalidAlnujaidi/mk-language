"""Tests for daemon.brain — the reasoning-brain tier resolver.

kinox's brain is **cloud by default (``glm-5.2`` on z.ai), local as the fallback**
— always. ``KINOX_BRAIN`` can name a different model or, set to ``local`` / ``off``
/ ``none`` / empty, disable the cloud brain (the hermetic/offline path). No
network: pure env → ``Tier`` logic.

The suite-wide ``conftest`` autouse fixture pins ``KINOX_BRAIN=local``; each test
here sets the env it needs explicitly, overriding that default.
"""

from __future__ import annotations

import pytest
from daemon.brain import DEFAULT_BRAIN_MODEL, brain_chain, brain_tier
from kernel.contracts import Tier

_LOCAL = Tier.model("qwen2.5:3b", where="local", backend="ollama")
_CLOUD = Tier.model("glm-5.2", where="cloud", backend="zai")


def test_default_is_cloud_glm(monkeypatch: pytest.MonkeyPatch) -> None:
    """Unset KINOX_BRAIN → the cloud GLM brain, not the local fallback."""
    monkeypatch.delenv("KINOX_BRAIN", raising=False)
    assert DEFAULT_BRAIN_MODEL == "glm-5.2"
    assert brain_tier(fallback=_LOCAL) == _CLOUD


def test_disabled_returns_local_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    """KINOX_BRAIN=local (and other disabling values) → the local fallback."""
    for value in ("local", "off", "none", ""):
        monkeypatch.setenv("KINOX_BRAIN", value)
        assert brain_tier(fallback=_LOCAL) == _LOCAL


def test_named_model_builds_cloud_tier(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("KINOX_BRAIN", "glm-4.7")
    monkeypatch.delenv("KINOX_BRAIN_BACKEND", raising=False)
    monkeypatch.delenv("KINOX_BRAIN_WHERE", raising=False)
    assert brain_tier() == Tier.model("glm-4.7", where="cloud", backend="zai")


def test_backend_and_where_overridable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("KINOX_BRAIN", "my-model")
    monkeypatch.setenv("KINOX_BRAIN_BACKEND", "vllm")
    monkeypatch.setenv("KINOX_BRAIN_WHERE", "local")
    assert brain_tier() == Tier.model("my-model", where="local", backend="vllm")


def test_chain_is_cloud_then_local_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("KINOX_BRAIN", raising=False)
    assert brain_chain(_LOCAL) == [_CLOUD, _LOCAL]


def test_chain_cloud_only_when_no_local(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("KINOX_BRAIN", raising=False)
    assert brain_chain(None) == [_CLOUD]


def test_chain_local_only_when_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("KINOX_BRAIN", "local")
    assert brain_chain(_LOCAL) == [_LOCAL]


def test_chain_empty_when_disabled_and_no_local(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("KINOX_BRAIN", "local")
    assert brain_chain(None) == []


def test_chain_dedups_when_brain_equals_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # A named brain identical to the fallback must not be listed twice (the
    # executor would otherwise retry the same tier on failure).
    monkeypatch.setenv("KINOX_BRAIN", "qwen2.5:3b")
    monkeypatch.setenv("KINOX_BRAIN_BACKEND", "ollama")
    monkeypatch.setenv("KINOX_BRAIN_WHERE", "local")
    assert brain_chain(_LOCAL) == [_LOCAL]
