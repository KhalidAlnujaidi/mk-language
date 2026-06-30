"""Session checkpoint and resume capabilities for the agent (CodeWhale Tier-2 #3).

Provides mechanisms to persist the `AgentState` to disk and load it back. This
allows an agent run that stopped due to a budget limit or transient error to
be resumed exactly where it left off, avoiding duplicate work and context loss.
"""

from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

from products.agent.loop import AgentState


class SessionStore:
    """Manages the persistence of AgentState to disk."""
    
    def __init__(self, directory: Path):
        self.directory = directory
        self.directory.mkdir(parents=True, exist_ok=True)

    def _path_for(self, session_id: str) -> Path:
        return self.directory / f"{session_id}.json"

    def save(self, session_id: str, state: AgentState) -> None:
        """Checkpoint the agent state to disk, keeping only the 20 most recent."""
        path = self._path_for(session_id)
        with path.open("w", encoding="utf-8") as f:
            json.dump(asdict(state), f, indent=2)
            
        # Garbage collect: keep only 20 most recent sessions
        try:
            sessions = sorted(
                self.directory.glob("*.json"), 
                key=lambda p: p.stat().st_mtime, 
                reverse=True
            )
            for old_session in sessions[20:]:
                old_session.unlink(missing_ok=True)
        except Exception:
            pass

    def load(self, session_id: str) -> AgentState | None:
        """Load a checkpointed state from disk, or None if not found."""
        path = self._path_for(session_id)
        if not path.exists():
            return None
        
        with path.open("r", encoding="utf-8") as f:
            data = json.load(f)
            
        # AgentState requires some conversion since it contains nested dataclasses/enums
        # However, AgentStep is a simple dataclass which json.dump handles if using asdict,
        # but json.load gives dicts. We must reconstruct AgentStep.
        from products.agent.loop import AgentStep
        
        steps = [
            AgentStep(
                kind=s.get("kind", ""),
                name=s.get("name", ""),
                detail=s.get("detail", ""),
                dag=s.get("dag")
            ) for s in data.get("steps", [])
        ]
        
        return AgentState(
            messages=data.get("messages", []),
            steps=steps,
            turns=data.get("turns", 0),
            tokens_spent=data.get("tokens_spent", 0),
            seen_reads=data.get("seen_reads", {}),
            ctx_chars=data.get("ctx_chars", 0),
            nudged=data.get("nudged", False),
            outcome_counts=data.get("outcome_counts", {}),
            blocked_streak=data.get("blocked_streak", 0),
            edit_fail_streak=data.get("edit_fail_streak", 0),
            self_heals_used=data.get("self_heals_used", 0)
        )
