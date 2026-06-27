"""Per-run token budget for the agent loop (CodeWhale Tier-2 + vision §9).

CodeWhale's thread goals track ``token_budget`` / ``tokens_used`` and stop a run
when the budget is spent. kinox's vision §9 names the same thing as a quick win:
"per-session token budget with a fail-soft early exit". This is the cost thesis
(#1) made into a hard, measured stop — the agent loop already caps *turns*
(fail-CLOSED), but turns are a proxy; tokens are the actual cost.

The budget is a pure, frozen *policy* — the running tally lives in the loop, so
this object stays immutable and trivially testable. Fail-direction is SOFT
(vision §9): when the budget is spent the loop *returns what it has* with a clear
reason, it does not raise — an exhausted budget is a graceful early exit, not an
error.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class TokenBudget:
    """A ceiling on total tokens (prompt + completion) for one agent run.

    ``limit`` of ``None`` means unlimited — the legacy behaviour, so an unset
    budget never changes a run. The tally (``spent``) is owned by the caller and
    passed in, keeping this policy object immutable.
    """

    limit: int | None = None

    def __post_init__(self) -> None:
        if self.limit is not None and self.limit < 0:
            raise ValueError("token budget limit must be non-negative")

    def exhausted(self, spent: int) -> bool:
        """True once *spent* reaches the limit (unlimited budgets never are)."""
        return self.limit is not None and spent >= self.limit

    def remaining(self, spent: int) -> int | None:
        """Tokens left before the ceiling, or ``None`` when unlimited."""
        if self.limit is None:
            return None
        return max(0, self.limit - spent)
