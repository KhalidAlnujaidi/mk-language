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

import json
import re
import shlex
import time
import anyio
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field

from daemon.exec import (
    BackendError,
    Call,
    ChainExhausted,
    ExecResult,
    Messages,
    execute,
    tier_label,
)
from kernel.contracts import EventRecord, Tier
from kernel.jsonutil import as_dict
from kernel.metrics import MetricsSink
from kernel.tracing import span

from products.agent.dag import DAGNode

class GuardBlocked(Exception):
    """Raised by a :data:`Guard` to abort a tool dispatch. The message is surfaced
    to the agent as its observation."""
    def __init__(self, message: str, dag: DAGNode | None = None):
        super().__init__(message)
        self.dag = dag

from products.agent.budget import TokenBudget
from products.agent.tools import ToolRegistry

#: Builds the executor ``Call`` for a given tool schema. Default binds the schema
#: to the real Ollama backend; tests inject a fake that returns scripted turns.
CallFactory = Callable[[list[dict[str, object]]], Call]

#: A pre-dispatch guard: ``(tool_name, arguments_json) -> None``.
#: Raising :class:`GuardBlocked` BLOCKS the call (fail-CLOSED, thesis #2).
Guard = Callable[[str, str], None]

#: Operational instructions for the agent.  The governing axioms (and, in
#: framework scope, kinox's internals) are injected as the preamble — axioms from
#: alignment/AXIOMS.md, framework internals from alignment/PREAMBLE.md — so they
#: are not restated here.  No duplication.
AGENT_SYSTEM_PROMPT = (
    "Accomplish the user's task by calling tools, observing results, and "
    "continuing until the task is done. Prefer find_skill BEFORE unfamiliar "
    "work — the skill corpus often already encodes how to do it. Read with "
    "intent, not breadth: open only files relevant to the task, never re-read "
    "a file you have already seen, and stop exploring the moment you have "
    "enough to act. When the task is complete, reply with a short plain-text "
    "summary and NO further tool calls. Be concise and honest; if you cannot "
    "do something, say so."
)

#: Idempotent read tools: calling them again with the same arguments yields the
#: same content, so a repeat is pure context rot — we serve a short pointer
#: instead of re-injecting the payload. (Deterministic ground truth, not a model
#: judging relevance — consistent with kinox's axioms.)
_IDEMPOTENT_READS = frozenset({"read_file", "list_dir", "find_skill", "load_skill"})


def _read_key(name: str, args_json: str) -> str | None:
    """A stable identity for an idempotent read call, or ``None`` if *name* is not
    an idempotent read (so its result must never be deduplicated)."""
    if name not in _IDEMPOTENT_READS:
        return None
    try:
        parsed: object = json.loads(args_json) if args_json else {}
    except json.JSONDecodeError:
        return None
    args = as_dict(parsed)  # untyped JSON → dict[str, object] (non-dict → {})
    if name in ("read_file", "list_dir"):
        return f"{name}:{str(args.get('path', '')).strip()}"
    if name == "find_skill":
        return f"find_skill:{str(args.get('query', '')).strip().lower()}"
    return f"load_skill:{str(args.get('name', '')).strip()}"


#: Markers in a tool observation that signal a write/edit did NOT take effect.
_EDIT_FAIL_MARKERS = (
    "(error", "(tool error", "error:", "failed", "no such", "could not",
    "not found", "(blocked", "traceback", "unable", "does not exist",
)


def _is_edit_attempt(name: str, args_json: str) -> bool:
    """True if this tool call *attempts to change a file* (vs. read/inspect).

    ``write_file`` is the built-in writer; an MCP editor surfaces under a name with
    ``edit``/``patch``/``write`` (e.g. ``token-optimizer__smart_edit``); a
    ``run_bash`` is an edit when it redirects into a file or runs an in-place
    mutator (``sed -i``/``tee``/``dd of=``/``truncate``). A read (``sed -n``,
    ``cat``, ``grep``) is deliberately NOT an edit, so read-heavy work never trips
    the no-write-progress gate.
    """
    n = name.lower()
    if n == "write_file" or any(h in n for h in ("edit", "patch", "write")):
        return True
    if n != "run_bash":
        return False
    try:
        parsed = as_dict(json.loads(args_json) if args_json else {})
    except json.JSONDecodeError:
        return False
    cmd = str(parsed.get("command", ""))
    toks = cmd.lower().split()
    if ">" in cmd or ">>" in cmd:
        return True
    if "tee" in toks or "truncate" in toks:
        return True
    if toks[:1] == ["sed"] and "-i" in toks:
        return True
    return toks[:1] == ["dd"] and any(t.startswith("of=") for t in toks)


def _edit_failed(name: str, observation: str) -> bool:
    """True if an edit attempt's *observation* shows it did not succeed.

    For ``run_bash`` the exit code is authoritative (``exit=0`` is success even with
    stderr noise; any non-zero is failure). For tool calls, an error/blocked marker
    in the observation means the edit did not take.
    """
    obs = observation.lower()
    if name.lower() == "run_bash":
        if "exit=0" in obs:
            return False
        if "exit=" in obs:
            return True
    return any(m in obs for m in _EDIT_FAIL_MARKERS)


@dataclass(frozen=True)
class AgentStep:
    """One observable event in a run: a tool call + its observation, or the
    final answer. Drives the TUI trace and the audit log."""

    kind: str  # "tool" | "final" | "blocked"
    name: str  # tool name (for "tool"/"blocked"), "" for "final"
    detail: str  # arguments (tool) or observation/answer text
    dag: dict[str, object] | None = None


@dataclass(frozen=True)
class AgentState:
    """A checkpoint of the agent loop's state to allow resumption/undo."""
    messages: Messages
    steps: list[AgentStep]
    turns: int
    tokens_spent: int
    seen_reads: dict[str, int]
    ctx_chars: int
    nudged: bool
    outcome_counts: dict[str, int]
    blocked_streak: int
    edit_fail_streak: int
    self_heals_used: int


@dataclass
class AgentResult:
    """The outcome of a run: the final text, the full step trace, the turn count,
    why it stopped (``"complete"`` | ``"max_turns"`` | ``"budget"`` | ``"stuck"``
    | ``"error"``), and the cumulative tokens spent (seeded by *spent_offset*, so
    a multi-run session can carry it forward — vision §9 per-session budget)."""

    final_text: str
    steps: list[AgentStep] = field(default_factory=list[AgentStep])
    turns: int = 0
    stopped: str = "complete"
    tokens_spent: int = 0
    state: AgentState | None = None


def _default_call_factory() -> CallFactory:
    """The production call factory: bind the tool schema to the real backend."""
    from daemon.backends import make_dispatch

    def factory(schema: list[dict[str, object]]) -> Call:
        return make_dispatch(tools=schema)

    return factory


async def _streamed_turn(
    tier: Tier,
    messages: Messages,
    tools: list[dict[str, object]],
    task_id: str,
    on_token: Callable[[str], None],
) -> ExecResult | None:
    """Stream one agent turn on *tier*: push content to *on_token* live and return
    an ``ExecResult`` identical in shape to :func:`execute`'s (tool_calls
    reassembled). Returns ``None`` on a stream failure so the caller falls back to
    the non-streaming chain — streaming is a fast primary path, never the only one.
    """
    from daemon.streaming import stream_agent_turn

    started = time.perf_counter()
    try:
        resp = await stream_agent_turn(
            tier, messages, on_content=on_token, tools=tools
        )
    except BackendError:
        return None
    event = EventRecord(
        task_id=task_id,
        kind="agent",
        tier=tier_label(tier),
        tokens_in=resp.tokens_in,
        tokens_out=resp.tokens_out,
        tokens_exact=resp.tokens_exact,
        latency_ms=(time.perf_counter() - started) * 1000.0,
    )
    return ExecResult(
        content=resp.content,
        tier_used=tier,
        event=event,
        tool_calls=resp.tool_calls,
        finish_reason=resp.finish_reason,
    )


async def run_agent(
    task: str,
    *,
    tier: Tier,
    registry: ToolRegistry,
    sink: MetricsSink,
    task_id: str,
    system_prompt: str = AGENT_SYSTEM_PROMPT,
    preamble: str = "",
    history: Messages | None = None,
    plan: str | None = None,
    max_turns: int = 8,
    stall_repeats: int = 3,
    stall_blocks: int = 5,
    stall_edit_fails: int = 9999,
    context_soft_chars: int = 40_000,
    token_budget: TokenBudget | None = None,
    spent_offset: int = 0,
    self_heal: bool = True,
    max_self_heals: int = 2,
    guard: Guard | None = None,
    call_factory: CallFactory | None = None,
    on_step: Callable[[AgentStep], None] | None = None,
    on_token: Callable[[str], None] | None = None,
    fallback: Tier | Sequence[Tier] | None = None,
    resume_from: AgentState | None = None,
) -> AgentResult:
    """Run the tool-calling loop for *task* and return an :class:`AgentResult`.

    Each turn calls the model (with the registry's tool schema); if it returns
    ``tool_calls`` they are guarded, dispatched, and their observations appended
    as ``role: tool`` messages before looping. The loop ends when the model
    returns no tool calls (``complete``), when the **logical convergence gate**
    trips (``stuck``), or when *max_turns* is reached (``max_turns``).

    The convergence gate is the *primary* stop and judges WHAT is called, not how
    many turns pass. Three no-progress signals, any of which stops the run early
    with ``stopped="stuck"`` and a clear reason:
      - **looping** — one ``(tool, args, observation)`` triple recurs *stall_repeats*
        times (keyed on the *result*, so a real edit→test→edit loop with changing
        output is not flagged);
      - **refusal-thrash** — *stall_blocks* tool calls in a row are refused;
      - **no-write-progress** — *stall_edit_fails* edit attempts fail without an
        intervening success (the edit-thrash case: an agent re-trying a change that
    *max_turns* remains only as a fail-CLOSED backstop: a hard ceiling on cost so an
    agent that never repeats and never converges still cannot spend unbounded budget.
    However, with *self_heal* (default ``True``), hitting ``max_turns`` or any stuck
    condition no longer terminates the run immediately. Instead the loop injects a
    corrective system message — telling the model to continue from where it left
    off (for ``max_turns``) or to change approach (for ``stuck``) — resets the
    progress counters, and continues with a fresh ``max_turns`` budget. This can
    happen at most *max_self_heals* times (default 2), giving the agent up to
    ``max_turns * (1 + max_self_heals)`` total turns before the fail-CLOSED backstop
    truly stops it. A token-budget exhaustion is NOT self-healed (that is a real cost
    ceiling, not a recoverable condition).
    *max_turns* remains only as a fail-CLOSED backstop: a hard ceiling on cost so an
    agent that never repeats and never converges still cannot spend unbounded budget.

    *token_budget* (vision §9), when given, caps the *total* tokens (prompt +
    completion, summed across turns) the run may spend. Unlike *max_turns* (a turn
    proxy), this is the real cost ceiling. It fails SOFT: once spent, the loop
    returns what it has with ``stopped="budget"`` rather than starting another
    expensive turn — a run may overshoot by at most the turn in flight. ``None``
    (default) is unlimited, so an unset budget never changes a run.

    *spent_offset* seeds the running token tally so a *budget continues across
    runs* (vision §9's per-**session** budget). A multi-turn caller — e.g. an
    interactive ``kx`` session, where each user message is a fresh ``run_agent`` —
    passes the cumulative spend so far; the budget then governs the whole session,
    not one run, and ``AgentResult.tokens_spent`` returns the new cumulative total
    to carry into the next run. ``0`` (default) is a fresh tally, unchanged.

    Context is governed deterministically to fight rot (no model judging
    relevance): an idempotent read repeated with the same arguments returns a
    short pointer instead of re-injecting its payload, and once accumulated tool
    output passes *context_soft_chars* the model is nudged ONCE to converge
    (soft — never a hard tool-call cap).

    *preamble* is project environment + axioms text (from
    :func:`products.agent.environment.build_preamble`) that is prepended to
    *system_prompt* so every session starts with full awareness of what kinox
    is, how it is structured, and what rules govern it. When *preamble* is empty
    (default), only *system_prompt* is used.

    *fallback*, when given and distinct from *tier*, is the second tier in the
    per-turn fallback chain: if the primary brain (e.g. a cloud model) errors on a
    turn, the executor falls through to it (fail SOFT, spec §6) so a cloud outage
    degrades to the local model rather than aborting the run.

    *history*, when given, is the prior conversation (OpenAI-format user/assistant
    messages) spliced in *between* the system prompt and this turn's *task* so a
    multi-turn agent session has memory of earlier turns. Only the caller's
    distilled turn pairs belong here — never this run's ephemeral tool scratch,
    which is rebuilt fresh each call.

    *plan*, when given, is a terse checklist a cheap local prehook planner
    (:func:`products.agent.planner.plan_task`) drafted for this task; it is
    injected as a HINT (an extra system message), never a contract — the guards
    and the model's judgment stay authoritative. It front-loads direction to curb
    wander before the expensive brain starts; absent/empty, the brain runs unguided.
    """
    factory = call_factory or _default_call_factory()
    chain: list[Tier] = [tier]
    if fallback is not None:
        if isinstance(fallback, Sequence) and not isinstance(fallback, str):
            for t in fallback:
                if t not in chain:
                    chain.append(t)
        elif fallback != tier:
            chain.append(fallback)
    schema = registry.schemas()
    if resume_from is not None:
        messages = list(resume_from.messages)
        result = AgentResult(
            final_text="",
            steps=list(resume_from.steps),
            turns=resume_from.turns,
            tokens_spent=resume_from.tokens_spent
        )
        seen_reads = dict(resume_from.seen_reads)
        ctx_chars = resume_from.ctx_chars
        nudged = resume_from.nudged
        outcome_counts = dict(resume_from.outcome_counts)
        blocked_streak = resume_from.blocked_streak
        edit_fail_streak = resume_from.edit_fail_streak
        spent_tokens = resume_from.tokens_spent
        self_heals_used = resume_from.self_heals_used
        start_turn = resume_from.turns
    else:
        compiled_prompt = (
            f"{preamble}\n\n---\n\n{system_prompt}" if preamble else system_prompt
        )
        messages: Messages = [
            {"role": "system", "content": compiled_prompt},
            *(history or []),
            {"role": "user", "content": task},
        ]
        if plan:
            messages.append(
                {
                    "role": "system",
                    "content": (
                        "[plan] A cheap local planner suggested this approach. Treat it "
                        "as a hint, not a contract — follow it only where it is correct, "
                        "and your guards and judgment remain authoritative:\n" + plan
                    ),
                }
            )
        result = AgentResult(final_text="", tokens_spent=spent_offset)
        seen_reads: dict[str, int] = {}
        ctx_chars = 0
        nudged = False
        outcome_counts: dict[str, int] = {}
        blocked_streak = 0
        edit_fail_streak = 0
        spent_tokens = spent_offset
        self_heals_used = 0
        start_turn = 0

    def _capture_state() -> AgentState:
        return AgentState(
            messages=list(messages),
            steps=list(result.steps),
            turns=result.turns,
            tokens_spent=spent_tokens,
            seen_reads=dict(seen_reads),
            ctx_chars=ctx_chars,
            nudged=nudged,
            outcome_counts=dict(outcome_counts),
            blocked_streak=blocked_streak,
            edit_fail_streak=edit_fail_streak,
            self_heals_used=self_heals_used,
        )

    with span("agent.run", {"kinox.task_id": task_id}):
      self_heal_active = True
      while self_heal_active:
        self_heal_active = False
        for turn_offset in range(max_turns):
            turn = start_turn + turn_offset
            if token_budget is not None and token_budget.exhausted(spent_tokens):
                # Fail-soft early exit (vision §9): return what we have, don't raise.
                # Checked before the turn counter so result.turns reflects *completed*
                # turns, and before execute() so no further call is spent.
                result.stopped = "budget"
                if not result.final_text:
                    result.final_text = (
                        f"(stopped: token budget of {token_budget.limit} reached after "
                        f"{result.turns} turns / {spent_tokens} tokens — raise the "
                        "budget or narrow the task)"
                    )
                result.state = _capture_state(); return result
            result.turns = turn + 1
            try:
                # Stream the turn when a token sink is wired (live answer, vision
                # §5.2): content renders as it arrives, tool_calls are reassembled.
                # None back means the stream failed → fall back to the full chain.
                exec_result = None
                if on_token is not None:
                    exec_result = await _streamed_turn(
                        chain[0], messages, schema, f"{task_id}-t{turn}", on_token
                    )
                if exec_result is None:
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
                result.state = _capture_state(); return result
            except BackendError as exc:
                result.final_text = f"(model unavailable: {exc})"
                result.stopped = "error"
                result.state = _capture_state(); return result

            # Every model turn is one boundary record (kind="agent").
            sink.record(exec_result.event)
            # Accrue this turn's tokens toward the budget (honest: counts may be None
            # when a backend did not report them — treat missing as zero, never guess).
            spent_tokens += (exec_result.event.tokens_in or 0) + (
                exec_result.event.tokens_out or 0
            )
            result.tokens_spent = spent_tokens  # current on every return below
            tool_calls = exec_result.tool_calls
            if not tool_calls:
                # Plain-text answer → the task is done.
                result.final_text = exec_result.content
                result.stopped = "complete"
                step = AgentStep("final", "", exec_result.content)
                result.steps.append(step)
                if on_step is not None:
                    on_step(step)
                result.state = _capture_state(); return result

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
                
                denial = None
                blocked_dag = None
                if guard is not None:
                    try:
                        guard(name, args_json)
                    except GuardBlocked as exc:
                        import traceback
                        tb = traceback.extract_tb(exc.__traceback__)
                        if tb:
                            loc = f"[{tb[-1].filename}:{tb[-1].lineno}]"
                        else:
                            loc = "[unknown location]"
                        denial = f"{loc} {exc}"
                        blocked_dag = exc.dag.to_dict() if exc.dag else None

                if denial is not None:
                    observation = f"(blocked by guard: {denial})"
                    step = AgentStep("blocked", name, denial, dag=blocked_dag)
                    kind = f"agent_tool_blocked:{name}"
                else:
                    read_key = _read_key(name, args_json)
                    if read_key is not None and read_key in seen_reads:
                        # Already retrieved this run → don't re-inject the payload.
                        observation = (
                            f"(already retrieved by an earlier {name} call this run — "
                            "result unchanged, omitted to preserve context)"
                        )
                        step = AgentStep("tool", name, args_json)
                        kind = f"agent_tool_cached:{name}"
                    else:
                        # Leaf "agent.tool" span of the trace (vision §7): the actual
                        # (deterministic) tool execution. No-op unless a tracer is set.
                        with span(f"agent.tool:{name}"):
                            observation = await anyio.to_thread.run_sync(
                                registry.dispatch, name, args_json
                            )
                        if read_key is not None:
                            seen_reads[read_key] = turn
                        step = AgentStep("tool", name, args_json)
                        kind = f"agent_tool:{name}"
                ctx_chars += len(str(observation))
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
                        "content": str(observation),
                    }
                )

                # Logical gate: did this action make progress, or is the agent stuck?
                outcome = f"{name}\x00{args_json}\x00{observation}"
                outcome_counts[outcome] = outcome_counts.get(outcome, 0) + 1
                blocked_streak = blocked_streak + 1 if denial is not None else 0
                # No-write-progress: count edit attempts that fail, reset on a success.
                # Non-edit calls (reads, searches) leave the streak untouched, so a
                # failing edit looped with re-reads still accumulates (the edit-thrash
                # case) while read-heavy work never trips it.
                if _is_edit_attempt(name, args_json):
                    if _edit_failed(name, str(observation)):
                        edit_fail_streak += 1
                    else:
                        edit_fail_streak = 0
                stuck: str | None = None
                if outcome_counts[outcome] >= stall_repeats:
                    stuck = (
                        f"the same action ({name}) produced the same result "
                        f"{outcome_counts[outcome]}× — no progress, looping"
                    )
                elif blocked_streak >= stall_blocks:
                    stuck = (
                        f"{blocked_streak} tool calls in a row were refused — the "
                        "approach is not working in this scope"
                    )
                elif edit_fail_streak >= stall_edit_fails:
                    stuck = (
                        f"{edit_fail_streak} edit attempts failed without a "
                        "successful write — the change is not taking; narrow it "
                        "or check the target"
                    )
                if stuck is not None:
                    if self_heal and self_heals_used < max_self_heals:
                        # Inject corrective message and reset for a fresh attempt.
                        self_heals_used += 1
                        messages.append({
                            "role": "system",
                            "content": (
                                f"[self-heal] You are stuck: {stuck}. "
                                "Change your approach: narrow the scope, try a "
                                "different tool, or break the task into smaller steps. "
                                "Do NOT repeat the same action that failed."
                            ),
                        })
                        outcome_counts.clear()
                        blocked_streak = 0
                        edit_fail_streak = 0
                        self_heal_active = True
                        break  # break inner for-loop, continue outer while
                    result.stopped = "stuck"
                    result.final_text = (
                        f"(stopped: {stuck}. Change approach or narrow the task — this \n"
                        "is a no-progress gate, not a turn-count cap.)"
                    )
                    result.state = _capture_state(); return result
            # Once the gathered context grows large, nudge the model to converge —
            # exactly once, so it costs ~one line and never nags. This governs context
            # rot (too much accumulated, signal lost) without a hard tool-call cap.
            if not nudged and ctx_chars >= context_soft_chars:
                nudged = True
                messages.append(
                    {
                        "role": "system",
                        "content": (
                            f"[context budget] You have gathered ~{ctx_chars} "
                            f"characters of tool output over {turn + 1} turns — "
                            "substantial. Stop gathering and act on what you have, or "
                            "give your final answer, unless a specific identified gap "
                            "remains. Do not re-read files you have already seen."
                        ),
                    }
                )

        if self_heal_active:
            # We broke out early due to a 'stuck' condition and already set up a self-heal.
            continue

        # Turn budget exhausted without a final answer (max_turns hit).
        # We allow continuous development if the agent is making progress (not stuck).
        if self_heal and self_heals_used < max_self_heals:
            messages.append({
                "role": "system",
                "content": (
                    f"[self-heal] You reached the {max_turns}-turn budget without "
                    "completing. Continue from where you left off — do NOT redo "
                    "work already done. Focus on the remaining steps and converge."
                ),
            })
            outcome_counts.clear()
            blocked_streak = 0
            edit_fail_streak = 0
            self_heals_used += 1
            self_heal_active = True
        else:
            result.stopped = "max_turns"
            if not result.final_text:
                result.final_text = (
                    f"(stopped after {max_turns} turns without completing — "
                    "the task may need more turns or a narrower scope)"
                )
            result.state = _capture_state(); return result