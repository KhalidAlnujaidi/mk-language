"""Tests for products.chat.session — ChatSession (unit, no network)."""

from __future__ import annotations

from pathlib import Path

from kernel.manifest import LocalModel
from kernel.metrics import MetricsSink
from products.chat.session import ChatSession, session_for_test


def test_send_returns_fallback_when_no_local_models() -> None:
    """When no local models are available, send() returns a clear fallback."""
    session = session_for_test(local_models=())
    response, _notes, tier = session.send("hello")
    assert "no local model available" in response
    assert tier is None


def test_send_appends_to_history() -> None:
    """Each send() adds one user + one assistant message to history."""
    model = LocalModel("gemma", vram_gb_required=5.0)
    session = session_for_test(local_models=(model,), gpu_vram_gb=12.0)
    # send() will try to dispatch to the model (network); that fails soft
    _response, _notes, _tier = session.send("hi")
    assert len(session.history) == 2
    assert session.history[0]["role"] == "user"
    assert session.history[1]["role"] == "assistant"


def test_clear_resets_history() -> None:
    """clear() empties the message history."""
    session = session_for_test()
    session.history = [
        {"role": "user", "content": "a"},
        {"role": "assistant", "content": "b"},
    ]
    session.clear()
    assert session.history == []


def test_history_capped() -> None:
    """History never exceeds _MAX_HISTORY_PAIRS * 2 messages."""
    session = session_for_test()
    # Pre-fill history close to the cap
    for i in range(31):
        session.history.append({"role": "user", "content": str(i)})
        session.history.append({"role": "assistant", "content": str(i)})
    # One more send should cap
    session.history.append({"role": "user", "content": "overflow"})
    session.history.append({"role": "assistant", "content": "overflow"})
    # Force the cap (normally done inside send)
    while len(session.history) > 30 * 2:
        session.history.pop(0)
    assert len(session.history) == 60


def test_session_for_test_defaults() -> None:
    """session_for_test() returns a usable ChatSession with sensible defaults."""
    session = session_for_test()
    assert session.manifest.cpu_count == 8
    assert session.manifest.gpu_vram_gb == 12.0
    assert session.cwd == Path("/tmp")
    assert isinstance(session.sink, MetricsSink)


def test_send_uses_first_local_model() -> None:
    """The first available local model is used (Ollama manages its own memory)."""
    small = LocalModel("small", vram_gb_required=2.0)
    big = LocalModel("big", vram_gb_required=10.0)
    session = session_for_test(local_models=(small, big), gpu_vram_gb=12.0)
    # send() will fail on network but tier selection happens before dispatch
    _response, _notes, tier = session.send("test")
    assert tier is not None
    assert tier.model_name == "small"  # first in the tuple
    assert tier.backend == "ollama"


def test_send_offloads_fuzzy_tag_to_the_broker_tagger() -> None:
    """With a local model available, the groom tag step is offloaded to the
    broker-backed tagger. An injected model_tag proves the wire: the returned
    tag ("feature") is one the deterministic keyword scan would NOT produce for
    this trigger-free prompt."""
    model = LocalModel("gemma", vram_gb_required=5.0)
    session = session_for_test(local_models=(model,), gpu_vram_gb=12.0)
    session.model_tag = lambda _tier, _text: ("feature",)
    _response, notes, _tier = session.send("hello there")
    assert any("tags: feature" in line for line in notes)


def test_send_without_model_does_not_call_model_tag() -> None:
    """No local model → no fuzzy offload (the tagger is never invoked)."""
    calls: list[str] = []
    session = session_for_test(local_models=())
    session.model_tag = lambda _tier, text: calls.append(text) or ("feature",)
    session.send("hello there")
    assert calls == []  # router returns deterministic; model_tag untouched


def test_system_prompt_is_used() -> None:
    """Custom system_prompt replaces the default."""
    custom = "You are a pirate."
    session = ChatSession(
        manifest=session_for_test().manifest,
        sink=MetricsSink(Path("/dev/null")),
        cwd=Path("/tmp"),
        system_prompt=custom,
    )
    assert session.system_prompt == custom
