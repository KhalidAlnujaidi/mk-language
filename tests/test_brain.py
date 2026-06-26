"""Tests for daemon.brain — the reasoning-brain tier resolver.

kinox's brain is **cloud by default (``glm-5.2`` on z.ai), local as the fallback**
— always. ``KINOX_BRAIN`` can name a different model or, set to ``local`` / ``off``
/ ``none`` / empty, disable the cloud brain (the hermetic/offline path). No
network: pure env → ``Tier`` logic.

The suite-wide ``conftest`` autouse fixture pins ``KINOX_BRAIN=local``; each test
here sets the env it needs explicitly, overriding that default.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from daemon.brain import (
    BRAIN_PRESETS,
    DEFAULT_BRAIN_MODEL,
    brain_chain,
    brain_tier,
    describe_brain,
    set_brain,
)
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
    # No OpenRouter key → the secondary tier is omitted, so the chain stays the
    # 2-tier default and existing behaviour is unchanged.
    monkeypatch.delenv("KINOX_BRAIN", raising=False)
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    assert brain_chain(_LOCAL) == [_CLOUD, _LOCAL]


def test_chain_cloud_only_when_no_local(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("KINOX_BRAIN", raising=False)
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    assert brain_chain(None) == [_CLOUD]


# --- the secondary (OpenRouter) tier and the 3-tier chain (the brain rule) -----

_OPENROUTER = Tier.model("z-ai/glm-4.6", where="cloud", backend="openrouter")


def test_secondary_off_without_key(monkeypatch: pytest.MonkeyPatch) -> None:
    """No OPENROUTER_API_KEY → no secondary tier (don't carry a tier that 401s)."""
    from daemon.brain import secondary_tier

    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    assert secondary_tier() is None


def test_secondary_on_when_keyed(monkeypatch: pytest.MonkeyPatch) -> None:
    """OPENROUTER_API_KEY set → the default GLM-on-OpenRouter secondary tier."""
    from daemon.brain import secondary_tier

    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-test")
    monkeypatch.delenv("KINOX_BRAIN_SECONDARY", raising=False)
    assert secondary_tier() == _OPENROUTER


def test_secondary_model_overridable(monkeypatch: pytest.MonkeyPatch) -> None:
    """OpenRouter is the experimentation surface — the model is env-overridable."""
    from daemon.brain import secondary_tier

    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-test")
    monkeypatch.setenv("KINOX_BRAIN_SECONDARY", "anthropic/claude-3.5-sonnet")
    assert secondary_tier() == Tier.model(
        "anthropic/claude-3.5-sonnet", where="cloud", backend="openrouter"
    )


def test_secondary_disabled_value_drops_tier(monkeypatch: pytest.MonkeyPatch) -> None:
    from daemon.brain import secondary_tier

    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-test")
    monkeypatch.setenv("KINOX_BRAIN_SECONDARY", "off")
    assert secondary_tier() is None


def test_chain_three_tier_when_openrouter_keyed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The brain rule: z.ai primary → OpenRouter secondary → local fallback."""
    monkeypatch.delenv("KINOX_BRAIN", raising=False)
    monkeypatch.delenv("KINOX_BRAIN_SECONDARY", raising=False)
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-test")
    assert brain_chain(_LOCAL) == [_CLOUD, _OPENROUTER, _LOCAL]


def test_chain_no_secondary_when_brain_is_local(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """KINOX_BRAIN=local → local-only, even with OpenRouter keyed (no cloud hop
    sneaks in behind a deliberately offline brain)."""
    monkeypatch.setenv("KINOX_BRAIN", "local")
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-test")
    assert brain_chain(_LOCAL) == [_LOCAL]


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


# --- selection: presets, description, persisted switching ---------------------


def test_presets_include_local_and_glm() -> None:
    labels = [p.label for p in BRAIN_PRESETS]
    assert any("local" in label for label in labels)
    assert any("glm-5.2" in label for label in labels)
    # the local preset has model=None (disables the cloud brain)
    assert BRAIN_PRESETS[0].model is None


def test_describe_brain_cloud_and_local(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("KINOX_BRAIN", raising=False)
    assert describe_brain() == "glm-5.2 (zai · cloud)"
    monkeypatch.setenv("KINOX_BRAIN", "local")
    assert describe_brain() == "local"


def test_set_brain_applies_live_and_persists(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    env_file = tmp_path / "env"
    monkeypatch.delenv("KINOX_BRAIN", raising=False)
    label = set_brain(
        "anthropic/claude-3.5-sonnet", "openrouter", "cloud", env_file=env_file
    )
    # live: os.environ updated so the next turn uses it
    assert label == "anthropic/claude-3.5-sonnet (openrouter · cloud)"
    assert brain_tier() == Tier.model(
        "anthropic/claude-3.5-sonnet", where="cloud", backend="openrouter"
    )
    # persisted: the env file carries the choice across restarts
    body = env_file.read_text()
    assert "KINOX_BRAIN=anthropic/claude-3.5-sonnet" in body
    assert "KINOX_BRAIN_BACKEND=openrouter" in body


def test_set_brain_local_disables_cloud(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    env_file = tmp_path / "env"
    set_brain(None, env_file=env_file)
    assert describe_brain() == "local"
    assert "KINOX_BRAIN=local" in env_file.read_text()


def test_upsert_preserves_other_keys(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    env_file = tmp_path / "env"
    env_file.write_text("# secrets\nZAI_API_KEY=keep-me\nKINOX_BRAIN=glm-5.2\n")
    set_brain(None, env_file=env_file)
    body = env_file.read_text()
    assert "ZAI_API_KEY=keep-me" in body  # unrelated secret untouched
    assert "KINOX_BRAIN=local" in body  # brain key replaced, not duplicated
    assert body.count("KINOX_BRAIN=") == 1
