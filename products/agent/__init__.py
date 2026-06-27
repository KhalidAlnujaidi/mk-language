"""kinox agent runtime — the tool-calling loop over the local broker.

``run_agent`` drives Perceive → Decide → Act → Observe on kinox's own model
broker; ``ToolRegistry`` (+ the ``default_registry`` toolset) gives it hands and
a bridge into the skill corpus. Pure logic — the TUI in ``products/chat`` calls
it; the model call is injectable for offline tests.
"""

from products.agent.coordinator import (
    OverlapError,
    Slice,
    agent_runner,
    assert_disjoint,
    combine_guards,
    ownership_guard,
    run_parallel,
)
from products.agent.environment import (
    build_axioms,
    build_preamble,
    session_preamble,
)
from products.agent.loop import (
    AGENT_SYSTEM_PROMPT,
    AgentResult,
    AgentStep,
    run_agent,
)
from products.agent.tools import (
    Tool,
    ToolRegistry,
    default_registry,
    project_root_guard,
)

__all__ = [
    "AGENT_SYSTEM_PROMPT",
    "AgentResult",
    "AgentStep",
    "OverlapError",
    "Slice",
    "Tool",
    "ToolRegistry",
    "agent_runner",
    "assert_disjoint",
    "build_axioms",
    "build_preamble",
    "combine_guards",
    "default_registry",
    "ownership_guard",
    "project_root_guard",
    "run_agent",
    "run_parallel",
    "session_preamble",
]
