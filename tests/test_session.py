"""Tests for products/agent/session.py state persistence."""

import json
from pathlib import Path

from products.agent.session import SessionStore
from products.agent.loop import AgentState, AgentStep


def test_session_store_save_and_load(tmp_path: Path) -> None:
    store = SessionStore(tmp_path / "sessions")
    
    # State with realistic data
    state = AgentState(
        messages=[{"role": "system", "content": "hi"}],
        steps=[AgentStep(kind="tool", name="read_file", detail="foo.txt")],
        turns=5,
        tokens_spent=1500,
        seen_reads={"read_file:foo.txt": 1},
        ctx_chars=1200,
        nudged=True,
        outcome_counts={"read_file\x00{}\x00bar": 2},
        blocked_streak=0,
        edit_fail_streak=1,
        self_heals_used=1,
    )
    
    store.save("test-session-123", state)
    
    # Verify file was created
    file_path = tmp_path / "sessions" / "test-session-123.json"
    assert file_path.exists()
    
    # Load and verify
    loaded = store.load("test-session-123")
    assert loaded is not None
    assert loaded.messages == state.messages
    assert len(loaded.steps) == 1
    assert loaded.steps[0].kind == "tool"
    assert loaded.steps[0].name == "read_file"
    assert loaded.turns == state.turns
    assert loaded.tokens_spent == state.tokens_spent
    assert loaded.seen_reads == state.seen_reads
    assert loaded.ctx_chars == state.ctx_chars
    assert loaded.nudged == state.nudged
    assert loaded.outcome_counts == state.outcome_counts
    assert loaded.blocked_streak == state.blocked_streak
    assert loaded.edit_fail_streak == state.edit_fail_streak
    assert loaded.self_heals_used == state.self_heals_used


def test_session_store_load_missing(tmp_path: Path) -> None:
    store = SessionStore(tmp_path / "sessions")
    loaded = store.load("missing-session")
    assert loaded is None
