"""Streaming chat replies via ChatSession.send_stream (vision §5.2 Layer 3).

Proves the session streams the brain's reply through ``on_delta`` and accumulates
the authoritative full text, updates history, and — crucially — falls back to the
non-streaming chain when streaming errors, so a reply is never lost.
"""

from __future__ import annotations

import asyncio

from daemon.exec import BackendError, ExecResult
from kernel.contracts import EventRecord
from kernel.manifest import LocalModel
from products.chat.session import session_for_test


def _session():
    # A fitting local model → a non-empty brain chain (local-only, no cloud key).
    return session_for_test(
        local_models=(LocalModel("small", 4.0),), gpu_vram_gb=12.0
    )


def test_send_stream_streams_and_accumulates(monkeypatch) -> None:
    async def fake_stream(_tier, _messages, **_kw):
        for delta in ("Hel", "lo", " world"):
            yield delta

    monkeypatch.setattr("daemon.streaming.stream_chat", fake_stream)
    sess = _session()
    got: list[str] = []
    text, _notes, tier = asyncio.run(sess.send_stream("hi", got.append))

    assert "".join(got) == "Hello world"  # streamed token-by-token
    assert text == "Hello world"  # authoritative full text
    assert tier is not None
    assert sess.history[-1]["content"] == "Hello world"  # remembered


def test_send_stream_falls_back_to_non_streaming_on_error(monkeypatch) -> None:
    async def boom_stream(_tier, _messages, **_kw):
        raise BackendError("backend does not stream")
        yield ""  # unreachable — makes this an async generator

    async def fake_execute(chain, _messages, *, call, task_id, kind="chat"):
        _ = call
        ev = EventRecord(task_id=task_id, kind=kind, tier="model:local:small")
        return ExecResult(content="fallback answer", tier_used=chain[0], event=ev)

    monkeypatch.setattr("daemon.streaming.stream_chat", boom_stream)
    monkeypatch.setattr("daemon.exec.execute", fake_execute)
    sess = _session()
    got: list[str] = []
    text, _notes, tier = asyncio.run(sess.send_stream("hi", got.append))

    assert text == "fallback answer"  # the non-streaming chain answered
    assert got == []  # no partial deltas were shown (stream failed before yielding)
    assert tier is not None
    assert sess.history[-1]["content"] == "fallback answer"


def test_send_stream_no_model_returns_hint(monkeypatch) -> None:
    # No local model and no cloud key → empty chain → the no-model hint, no stream.
    sess = session_for_test(local_models=(), gpu_vram_gb=None, cloud=False)
    got: list[str] = []
    text, _notes, tier = asyncio.run(sess.send_stream("hi", got.append))
    assert "no model available" in text
    assert tier is None
    assert got == []
