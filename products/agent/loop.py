"""The tool-calling agent loop (vision §5, agent phase).

Replicates the universal agent loop (Perceive → Decide → Act → Observe → repeat)
on kinox's own broker: call the local model with a tool schema, and while it
answers with ``tool_calls``, dispatch each through the :class:`ToolRegistry`,
feed the observations back as ``role: tool`` messages, and loop — until the model
answers with plain text (done) or the turn budget is hit (fail-CLOSED).

The tool-call format is the **OpenAI standard** (``message.tool_calls`` with
``function.name`` + JSON ``arguments``) because that is exactly what kinox's
Ollama backend emits natively — no token-parsing, the protocol does it. The
harvested skills use Anthropic ``tool_use`` blocks only because they run inside
Claude Code; here the backend dictates the shape, and reusing the standard the
backend already speaks is the Rule-Zero choice.

Pure logic, no TTY. The model call is injected (*call_factory*) so the suite runs
offline with a scripted backend — the same boundary-injection discipline as
``daemon/exec.py`` and ``products/chat/session.py``.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass, field

from daemon.exec import BackendError, Call, ChainExhausted, Messages, execute
from kernel.contracts import EventRecord, Tier
from kernel.jsonutil import as_dict
from kernel.metrics import MetricsSink

from products.agent.tools import ToolRegistry

#: Builds the executor ``Call`` for a given tool schema. Default binds the schema
#: to the real Ollama backend; tests inject a fake that returns scripted turns.
CallFactory = Callable[[list[dict[str, object]]], Call]

#: A pre-dispatch guard: ``(tool_name, arguments_json) -> denial reason | None``.
#: Returning a string BLOCKS the call (fail-CLOSED, thesis #2); ``None`` allows it.
Guard = Callable[[str, str], "str | None"]

AGENT_SYSTEM_PROMPT = (
    "You are kinox, a governed local-first coding agent. You accomplish the "
    "user's task by calling tools, observing results, and continuing until the "
    "task is done. Prefer find_skill BEFORE unfamiliar work — the skill corpus "
    "often already encodes how to do it. When the task is complete, reply with a "
    "short plain-text summary and NO further tool calls. Be concise and honest; "
    "if you cannot do something, say so."
)


@dataclass(frozen=True)
class AgentStep:
    """One observable event in a run: a tool call + its observation, or the
    final answer. Drives the TUI trace and the audit log."""

    kind: str  # "tool" | "final" | "blocked"
    name: str  # tool name (for "tool"/"blocked"), "" for "final"
    detail: str  # arguments (tool) or observation/answer text


@dataclass
class AgentResult:
    """The outcome of a run: the final text, the full step trace, the turn count,
    and why it stopped (``"complete"`` | ``"max_turns"`` | ``"error"``)."""

    final_text: str
    steps: list[AgentStep] = field(default_factory=list[AgentStep])
    turns: int = 0
    stopped: str = "complete"


def _default_call_factory() -> CallFactory:
    """The production call factory: bind the tool schema to the real backend."""
    from daemon.backends import make_dispatch

    def factory(schema: list[dict[str, object]]) -> Call:
        return make_dispatch(tools=schema)

    return factory


async def run_agent(
    task: str,
    *,
    tier: Tier,
    registry: ToolRegistry,
    sink: MetricsSink,
    task_id: str,
    system_prompt: str = AGENT_SYSTEM_PROMPT,
    max_turns: int = 8,
    guard: Guard | None = None,
    call_factory: CallFactory | None = None,
    on_step: Callable[[AgentStep], None] | None = None,
    fallback: Tier | None = None,
) -> AgentResult:
    """Run the tool-calling loop for *task* and return an :class:`AgentResult`.

    Each turn calls the model (with the registry's tool schema); if it returns
    ``tool_calls`` they are guarded, dispatched, and their observations appended
    as ``role: tool`` messages before looping. The loop ends when the model
    returns no tool calls (``complete``) or *max_turns* is reached
    (``max_turns`` — fail-CLOSED so a runaway cannot spin forever).

    *fallback*, when given and distinct from *tier*, is the second tier in the
    per-turn fallback chain: if the primary brain (e.g. a cloud model) errors on a
    turn, the executor falls through to it (fail SOFT, spec §6) so a cloud outage
    degrades to the local model rather than aborting the run.
    """
    factory = call_factory or _default_call_factory()
    chain = [tier] if fallback is None or fallback == tier else [tier, fallback]
    schema = registry.schemas()
    messages: Messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": task},
    ]
    result = AgentResult(final_text="")

    for turn in range(max_turns):
        result.turns = turn + 1
        try:
            exec_result = await execute(
                chain,
                messages,
                call=factory(schema),
                task_id=f"{task_id}-t{turn}",
                kind="agent",
            )
        except ChainExhausted as exc:
            # Honest observability (vision §4.6): the failure boundary is logged
            # too, so the metrics log never has a silent gap.
            sink.record(exc.event)
            result.final_text = "(model unavailable: fallback chain exhausted)"
            result.stopped = "error"
            return result
        except BackendError as exc:
            result.final_text = f"(model unavailable: {exc})"
            result.stopped = "error"
            return result

        # Every model turn is one boundary record (kind="agent").
        sink.record(exec_result.event)
        tool_calls = exec_result.tool_calls
        if not tool_calls:
            # Plain-text answer → the task is done.
            result.final_text = exec_result.content
            result.stopped = "complete"
            step = AgentStep("final", "", exec_result.content)
            result.steps.append(step)
            if on_step is not None:
                on_step(step)
            return result

        # The model asked for tools. Record the assistant turn (OpenAI requires
        # the tool_calls message to precede the tool results), then dispatch.
        messages.append(
            {
                "role": "assistant",
                "content": exec_result.content or "",
                "tool_calls": tool_calls,
            }
        )
        for tc in tool_calls:
            fn = as_dict(tc.get("function"))
            name = str(fn.get("name", ""))
            raw_args = fn.get("arguments")
            args_json = raw_args if isinstance(raw_args, str) else "{}"

            started = time.perf_counter()
            denial = guard(name, args_json) if guard is not None else None
            if denial is not None:
                observation = f"(blocked by guard: {denial})"
                step = AgentStep("blocked", name, denial)
                kind = f"agent_tool_blocked:{name}"
            else:
                observation = registry.dispatch(name, args_json)
                step = AgentStep("tool", name, args_json)
                kind = f"agent_tool:{name}"
            # Every agent action is a boundary record — the auditable action log
            # (vision §4.6). Tool dispatch is deterministic, so tier reflects that.
            sink.record(
                EventRecord(
                    task_id=f"{task_id}-t{turn}",
                    kind=kind,
                    tier="deterministic",
                    latency_ms=(time.perf_counter() - started) * 1000.0,
                )
            )
            result.steps.append(step)
            if on_step is not None:
                on_step(step)

            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": str(tc.get("id", "")),
                    "content": observation,
                }
            )

    # Turn budget exhausted without a final answer → stop (fail-CLOSED).
    result.stopped = "max_turns"
    if not result.final_text:
        result.final_text = (
            f"(stopped after {max_turns} turns without completing — "
            "the task may need more turns or a narrower scope)"
        )
    return result
