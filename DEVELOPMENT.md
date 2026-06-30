# KINOX DEVELOPMENT — Phase 5: Eval Harness + Chat Polish + Multi-Agent Protocol

> **This file is the coordination surface for multi-agent development on kinox.**
> Every agent that works on this repo MUST read this file first. It tells you
> what you are allowed to touch and what you must leave alone.
>
> **The jail is voluntary but binding.** Like all kinox governance, it is a
> speed bump, not a wall (Constitution Hard Truth #1). But an agent that
> violates its scope is an agent whose work will be reverted. Respect the
> boundaries.
>
> Generated: 2026-06-24 · Phase: 5 · Branch: `main` (tasks branch off `main`)

---

## Agent Protocol

### Identity

Every agent claims an identity before touching any file. The format is:

```
{whale_name}-{claim_timestamp}
```

| Component | Format | Example | Source |
|---|---|---|---|
| `whale_name` | lowercase, from the pool below | `narwhal` | Agent picks first unclaimed name from §Agent Pool |
| `claim_timestamp` | `YYYYMMDD-HHMMSS` UTC | `20260624-143052` | `date -u +%Y%m%d-%H%M%S` at claim time |

Full identity example: `narwhal-20260624-143052`

**Why a whale name?** kinox already uses whale names for sub-agents (Beluga,
Orca, etc.). This convention is established. The name is human-readable, easy to
spot in git logs, and carries no implication about model capability or rank —
all agents are equal peers under the same constraints.

**Why a timestamp instead of a hash?** A hash of what? The model name + prompt
changes every turn. A hash of model + timestamp just stretches a nonce into
something less readable. The timestamp IS the nonce — two agents claiming the
same task in the same second is astronomically unlikely, and if it happens, the
second agent to commit will see the conflict on pull and retry.

### Claiming a Task

1. Read this file. Find an **UNCLAIMED** task (status is `UNCLAIMED`).
2. Select a whale name from the §Agent Pool — pick the **first unclaimed** name
   (the agent whose name is closest to the top of the pool and not currently
   listed in any task's `claimed_by` field).
3. Compute your timestamp: run `date -u +%Y%m%d-%H%M%S`.
4. Edit this file: change the task's `status` from `UNCLAIMED` to `CLAIMED`,
   and set `claimed_by` to your identity.
5. Create the task's branch: `git checkout -b {branch} main`.
6. Commit immediately: `git commit -m "claim: {identity} claims {task_id}"`.
7. Push the branch. Begin work.

### Releasing a Task

When the task is complete and all acceptance criteria are met:

1. Update this file: change `status` to `COMPLETE`, add `completed_at` with
   the UTC timestamp of completion.
2. Commit on the task branch.
3. Merge to `main` with `--no-ff`.
4. The whale name returns to the pool for future phases.

If the task cannot be completed (blocked, wrong approach):

1. Update this file: change `status` back to `UNCLAIMED`, clear `claimed_by`.
2. Add a `blocked_reason` note.
3. Commit on the task branch. Push. Do NOT merge broken work to `main`.

### File Ownership — The Jail

Every task declares exactly which files it may touch:

- **`files_owned`**: The agent may CREATE, MODIFY, or DELETE these files.
- **`files_readonly`**: The agent may READ these files but MUST NOT modify them.
- **Everything else is FORBIDDEN.** This is a fail-closed default (thesis #2).

Before touching any file, the agent MUST verify:
1. Is this file listed in my task's `files_owned`? → proceed.
2. Is this file listed in my task's `files_readonly`? → read only, DO NOT write.
3. Not listed? → DO NOT TOUCH. If you need it, update this file first and
   negotiate with the affected task's agent.

**Protected files** — the following are ALWAYS read-only for all tasks, regardless
of what individual task specs say:

- `alignment/CONSTITUTION.md` — the immutable core
- `alignment/CLAUDE.md` — working conventions
- `vision.md` — the spine
- `DEVELOPMENT.md` — this file (tasks may only update their own `status`,
  `claimed_by`, `completed_at`, and `blocked_reason` fields)
- `kernel/contracts.py` — the kernel's load-bearing types
- `tests/test_architecture.py` — the architecture guardrail

### Pre-Ingestion Hook (Future — TASK-5-4)

When TASK-5-4 is complete, every kinox agent session will read this file
automatically via a new groom stage (`products/groom/stages/jail.py`). The stage
will:

1. Parse `DEVELOPMENT.md` to find the agent's claimed task.
2. Inject the task's `files_owned` and `files_readonly` lists as alignment
   context into the agent's system prompt.
3. The agent's Constitution then enforces the jail.

Until TASK-5-4 ships, agents self-enforce by reading this file manually at
session start. The mechanism is the same; the automation just removes the
manual step.

---

## Agent Pool

Whale names in priority order (first unclaimed → first used). This pool is drawn
from the kinox sub-agent convention. 15 names; if exhausted, append new ones.

| # | Name | Convention |
|---|---|---|
| 1 | Beluga | default sub-agent |
| 2 | Orca | default sub-agent |
| 3 | Narwhal | default sub-agent |
| 4 | Moby | default sub-agent |
| 5 | Spermy | default sub-agent |
| 6 | Blue | default sub-agent |
| 7 | Pilot | default sub-agent |
| 8 | Minke | default sub-agent |
| 9 | Humpback | default sub-agent |
| 10 | Gray | default sub-agent |
| 11 | Fin | default sub-agent |
| 12 | Bowhead | default sub-agent |
| 13 | Sei | default sub-agent |
| 14 | Bryde | default sub-agent |
| 15 | Right | default sub-agent |

---

## File Ownership Map

Quick-reference grid. "R" = read-only, "O" = owned by task, blank = forbidden.

| File / Directory | T5-1 | T5-2 | T5-3 | T5-4 | T5-5 |
|---|---|---|---|---|---|
| `evals/schema.py` | O | R | | | |
| `evals/tasks/*.yaml` | O | R | | | |
| `evals/runner.py` | | O | | | |
| `evals/store.py` | | O | | | |
| `evals/__init__.py` | R | O | | | |
| `tests/eval/test_schema.py` | O | | | | |
| `tests/eval/test_runner.py` | | O | | | |
| `tests/eval/test_store.py` | | O | | | |
| `tests/eval/test_jail.py` | | | | O | |
| `products/chat/session.py` | | | O | | |
| `products/chat/app.py` | | | O | | |
| `tests/test_chat_session.py` | | | O | | |
| `tests/test_chat_app.py` | | | O | | |
| `products/groom/stages/jail.py` | | | | O | |
| `products/groom/pipeline.py` | | | | O | R |
| `daemon/scheduler.py` | | | | | O |
| `daemon/server.py` | | | | | O |
| `tests/test_broker_scheduler.py` | | | | | O |
| `kernel/contracts.py` | R | R | R | R | R |
| `kernel/manifest.py` | R | R | R | R | R |
| `kernel/metrics.py` | R | R | R | R | R |
| `kernel/router.py` | R | | | | R |

---

## Tasks

---

### TASK-5-1 — Golden Eval Set Schema + Tasks

| Field | Value |
|---|---|
| **Status** | `CLAIMED` |
| **Claimed by** | `beluga-20260624-173913` |
| **Branch** | `g5-1-eval-schema` |
| **Depends on** | nothing |
| **Depended on by** | TASK-5-2 (schema consumer) |

**Files owned:**
- `evals/schema.py` — the `EvalTask` dataclass + `EvalResult` dataclass
- `evals/tasks/*.yaml` — 20–50 behavioral eval tasks
- `tests/eval/test_schema.py` — TDD tests

**Files read-only:**
- `kernel/contracts.py` — `Tier`, `Annotation`, `EventRecord`, `FailDirection`
- `kernel/manifest.py` — `Manifest`, `LocalModel`
- `kernel/metrics.py` — `MetricsSink`
- `evals/__init__.py` — existing eval infrastructure

**Must NOT touch:** `products/**`, `daemon/**`, `kx`, `kin`, `kernel/` (except reads)

**Description:**

Define the schema that makes eval tasks machine-readable and behavioral.
A kinox eval task is NOT exact-output matching. It is a **behavioral assertion**:
"under these conditions, did the system do the right thing?"

The `EvalTask` schema must capture:
- `id`: unique slug (e.g. `redact-api-key`)
- `description`: human-readable summary
- `setup`: filesystem state to create before the test (dict of path→content)
- `prompt`: the user input to feed through the groom pipeline or full session
- `assertions`: list of behavioral checks:
  - `kind`: `"redacted"` (secret not in output), `"routed"` (tier matches expected),
    `"refused"` (destructive command denied), `"contains"` (text present),
    `"not_contains"` (text absent), `"schema"` (output matches JSON schema)
  - `target`: what to check (e.g. `"annotation.lines"`, `"response_text"`,
    `"tier.model_name"`, `"tier.where"`)
  - `expected`: the expected value or pattern
- `tags`: list of categories (e.g. `["groom", "redact"]`, `["router", "local"]`)

The `EvalResult` schema must capture:
- `task_id`: which task was run
- `passed`: bool
- `assertion_results`: list of per-assertion pass/fail + actual value
- `duration_ms`: how long it took
- `trace`: the EventRecord IDs involved

Then write 20–50 eval tasks covering:
- Secret redaction (API keys, tokens, passwords in various formats)
- Router behavior (deterministic vs fuzzy vs reasoning tier selection)
- Guard denial (destructive commands, protected file writes)
- Groom pipeline (expansion, context attachment, tagging)
- Fail-direction (CLOSED gate denies, SOFT gate degrades)
- Correction detection (correction_of field populated)
- Manifest honesty (null vs fabricated false)
- Broker fallback (model unavailable → fallback chain)
- Outbox durability (append then mark_done round-trips)

**Acceptance:**
- [ ] `EvalTask` and `EvalResult` are dataclasses with type-safe fields
- [ ] Schema validation: loading a YAML task rejects unknown fields
- [ ] 20+ YAML task files in `evals/tasks/`, each valid against the schema
- [ ] Each task has at least one behavioral assertion
- [ ] Categories cover all of: groom, router, guard, broker, corrections, manifest
- [ ] `uv run pytest tests/eval/test_schema.py -q` green
- [ ] Full suite + ruff + pyright + architecture guardrail green

---

### TASK-5-2 — Eval Regression Runner + Store

| Field | Value |
|---|---|
| **Status** | `UNCLAIMED` |
| **Claimed by** | — |
| **Branch** | `g5-2-eval-runner` |
| **Depends on** | TASK-5-1 (schema — can start in parallel with the schema class definitions) |
| **Depended on by** | future self-evolving work |

**Files owned:**
- `evals/runner.py` — `run_eval_set(tasks, *, manifest, sink) → list[EvalResult]`
- `evals/store.py` — `record_evolution(before, after)` → stores eval diffs
- `evals/__init__.py` — may add public exports
- `tests/eval/test_runner.py` — TDD tests
- `tests/eval/test_store.py` — TDD tests

**Files read-only:**
- `evals/schema.py` — `EvalTask`, `EvalResult` (from TASK-5-1)
- `evals/tasks/*.yaml` — task definitions (from TASK-5-1)
- `kernel/contracts.py`, `kernel/manifest.py`, `kernel/metrics.py`

**Must NOT touch:** `products/**`, `daemon/**`, `kx`, `kin`

**Description:**

Build the runner that makes the eval set executable. `run_eval_set` takes a list
of `EvalTask` objects, a `Manifest`, and a `MetricsSink`, and returns a list of
`EvalResult` objects — one per task, with per-assertion pass/fail.

The runner must:
1. For each task, set up the filesystem state from `task.setup`
2. Run the appropriate kinox function (groom pipeline, router, guard, broker)
   depending on the assertion's `target`
3. Evaluate each assertion against the actual output
4. Record the result
5. Tear down any filesystem state (temp dirs)
6. Never raise — a failing assertion is a recorded failure, not a crash

The store (`record_evolution`) must:
- Accept `before: list[EvalResult]` and `after: list[EvalResult]`
- Write an evolution artifact to `evolutions/{timestamp}-{slug}.json`
- Include: which tasks improved, which regressed, which stayed the same
- The artifact is the input to the self-evolving proposer's gate stage

**Acceptance:**
- [ ] `run_eval_set` executes all tasks and returns one `EvalResult` per task
- [ ] A task with a passing assertion produces `EvalResult(passed=True)`
- [ ] A task with a failing assertion produces `EvalResult(passed=False)` with
      the actual value captured
- [ ] Setup/teardown is clean — no temp files leak
- [ ] `record_evolution` writes a valid evolution artifact to `evolutions/`
- [ ] Runner handles a missing `evals/tasks/` directory gracefully (empty results)
- [ ] `uv run pytest tests/eval/test_runner.py tests/eval/test_store.py -q` green
- [ ] Full suite + ruff + pyright + architecture guardrail green

---

### TASK-5-3 — Chat Session Save/Load + Commands

| Field | Value |
|---|---|
| **Status** | `UNCLAIMED` |
| **Claimed by** | — |
| **Branch** | `g5-3-chat-save` |
| **Depends on** | nothing |
| **Depended on by** | nothing |

**Files owned:**
- `products/chat/session.py` — `save()`, `load()`, `list_sessions()` methods
- `products/chat/app.py` — `/save`, `/load`, `/sessions` commands
- `tests/test_chat_session.py` — extend with save/load tests
- `tests/test_chat_app.py` — extend with command tests

**Files read-only:**
- `kernel/contracts.py`, `kernel/manifest.py`, `kernel/metrics.py`

**Must NOT touch:** `evals/**`, `daemon/**`, `products/groom/**`, `products/launcher/**`, `kx`, `kin`

**Description:**

Currently, `/quit` discards the conversation. Add persistence so sessions can
be saved and resumed.

`ChatSession` gains:
- `save(name: str) → Path` — writes the full history (system prompt + all
  user/assistant messages) to `~/.kinox/sessions/{name}.jsonl`. Returns the
  file path. Overwrites if the name already exists.
- `load(name: str) → ChatSession` — class method. Reads
  `~/.kinox/sessions/{name}.jsonl` and returns a new `ChatSession` with
  restored history. Raises `FileNotFoundError` if the session doesn't exist.
- `list_sessions() → list[str]` — static method. Lists saved session names
  (sorted by modification time, newest first) from `~/.kinox/sessions/`.

The chat TUI gains three new commands:
- `/save <name>` — saves the current session. Prints confirmation with file path.
- `/load <name>` — replaces the current session with the loaded one. Prints
  a summary (N turns restored).
- `/sessions` — lists all saved sessions with turn count and age.

Sessions directory is created on first save if it doesn't exist. JSONL format:
one JSON object per line, with `role`, `content`, and `timestamp` fields.

**Acceptance:**
- [ ] `save("test")` writes the session to `~/.kinox/sessions/test.jsonl`
- [ ] `load("test")` restores the session with identical history
- [ ] `list_sessions()` returns saved names in mtime order
- [ ] `/save`, `/load`, `/sessions` commands work in the TUI
- [ ] Loading a nonexistent session prints a clear error, doesn't crash
- [ ] Saving overwrites an existing session of the same name (no prompt)
- [ ] Sessions directory auto-created on first save
- [ ] `uv run pytest tests/test_chat_session.py tests/test_chat_app.py -q` green
- [ ] Full suite + ruff + pyright + architecture guardrail green

---

### TASK-5-4 — Pre-Ingestion Jail Hook (Groom Stage)

| Field | Value |
|---|---|
| **Status** | `UNCLAIMED` |
| **Claimed by** | — |
| **Branch** | `g5-4-jail-hook` |
| **Depends on** | nothing |
| **Depended on by** | future multi-agent sessions |

**Files owned:**
- `products/groom/stages/jail.py` — the groom stage that reads DEVELOPMENT.md
- `tests/eval/test_jail.py` — TDD tests
- `products/groom/pipeline.py` — add `jail` to the stage import list (read-only
  change: one import line + one stage call)

**Files read-only:**
- `DEVELOPMENT.md` — read to extract task scope
- `kernel/contracts.py` — `FailDirection`, `Annotation`

**Must NOT touch:** `evals/runner.py`, `evals/schema.py`, `products/chat/**`,
`daemon/**`, `kx`, `kin`

**Description:**

Create a new groom stage, `jail`, that reads `DEVELOPMENT.md` from the repo root
and injects the agent's task scope as alignment context.

The stage follows the existing stage pattern (see `products/groom/stages/context.py`
for reference):
- Declares `FAIL_DIRECTION = FailDirection.SOFT` — if DEVELOPMENT.md is missing
  or malformed, the stage degrades silently (no jail means no extra constraints,
  not a blocked session).
- Exports a single public function: `gather(cwd: Path, *, agent_id: str | None = None) → JailResult`
- `JailResult` is a dataclass with `lines: tuple[str, ...]` — the constraint
  lines to inject into the agent's context.

Logic:
1. Locate `DEVELOPMENT.md` at `cwd` (the repo root from the session scope).
2. If the file doesn't exist, return `JailResult(())` — no constraints.
3. Parse the file to extract:
   - The task whose `claimed_by` matches `agent_id`
   - The task's `files_owned` and `files_readonly` lists
4. If `agent_id` is None or no matching task is found, return `JailResult(())`.
5. If a matching task is found, return constraint lines like:
   ```
   [jail · TASK-5-4 · claimed by beluga-20260624-143052]
   You may modify: products/groom/stages/jail.py, tests/eval/test_jail.py
   You may read: DEVELOPMENT.md, kernel/contracts.py
   Everything else is FORBIDDEN — DO NOT TOUCH.
   ```
6. Wire into `products/groom/pipeline.py` as a new stage (after `context`,
   before `tag`). The stage is deterministic (no model call — thesis #1).

The `agent_id` is passed through the groom pipeline from the chat session
or agent adapter. When not in a multi-agent development context, `agent_id`
is `None` and the stage is a no-op.

**Acceptance:**
- [ ] `jail.py` follows the existing stage pattern (FAIL_DIRECTION, dataclass result, public gather function)
- [ ] When DEVELOPMENT.md exists and agent_id matches a claimed task, constraint lines are returned
- [ ] When DEVELOPMENT.md is missing, returns empty result (no crash)
- [ ] When agent_id is None, returns empty result (no crash)
- [ ] When agent_id doesn't match any task, returns empty result
- [ ] Groom pipeline includes the jail stage (after context, before tag)
- [ ] Stage is deterministic — no model call, pure file parse
- [ ] `uv run pytest tests/eval/test_jail.py -q` green
- [ ] Full suite + ruff + pyright + architecture guardrail green

---

### TASK-5-5 — Broker Async Scheduler

| Field | Value |
|---|---|
| **Status** | `UNCLAIMED` |
| **Claimed by** | — |
| **Branch** | `g5-5-broker-scheduler` |
| **Depends on** | nothing |
| **Depended on by** | future multi-user broker work |

**Files owned:**
- `daemon/scheduler.py` — `Scheduler` class with async queue, priority, concurrency
- `daemon/server.py` — wire the scheduler into the FastAPI app
- `tests/test_broker_scheduler.py` — TDD tests

**Files read-only:**
- `daemon/registry.py` — model registry (used by scheduler for VRAM awareness)
- `daemon/resources.py` — resource monitor (used by scheduler for capacity)
- `daemon/backends.py` — backend adapter dispatch
- `kernel/contracts.py` — `Tier`, `FailDirection`
- `kernel/manifest.py` — `Manifest`, `LocalModel`

**Must NOT touch:** `products/**`, `evals/**`, `kx`, `kin`, `kernel/` (except reads)

**Description:**

Turn the broker from synchronous single-request into an async multi-request
scheduler. Designed in vision §5.3:

> **Scheduling** — async queue, per-GPU concurrency limits, priority (grooming/
> review high, long sessions low). `warm_set_size` is a function of available
> VRAM, not a static config, and auto-tunes down on observed OOM.

The `Scheduler` class:
- Accepts an `asyncio.Queue` of `ScheduleRequest` items
- Each request carries: `tier`, `messages`, `task_id`, `kind` (groom/review/chat), `priority`
- Priority ordering: grooming > review > chat (grooming is fast and blocking
  the user's prompt; chat sessions are long and can wait)
- Per-GPU concurrency limit: at most `N` requests run concurrently on the same
  GPU backend, where `N` is a function of available VRAM / model VRAM estimate
- When concurrency is at capacity, new requests queue
- When a request completes (or fails), the next queued request is dispatched
- OOM detection: if a dispatch fails with an OOM-like error, reduce the
  concurrency limit for that backend and retry
- Exposes `status()` → dict with queue depth, active requests, per-backend
  concurrency limits, and recent OOM events

Wire into `daemon/server.py`:
- Replace the synchronous `execute()` call in the chat/completions endpoint
  with `await scheduler.submit(request)`
- The existing synchronous path remains for backward compatibility (gated by
  a config flag: `KINOX_ASYNC_BROKER=1`)

**Acceptance:**
- [ ] `Scheduler.submit()` enqueues a request and returns when it completes
- [ ] Higher-priority requests are dispatched before lower-priority ones
- [ ] Per-GPU concurrency limit is enforced (N concurrent, N+1th queues)
- [ ] OOM detection reduces concurrency limit for the affected backend
- [ ] `status()` returns accurate queue depth and active request count
- [ ] Async path is gated behind `KINOX_ASYNC_BROKER=1`; sync path unchanged
- [ ] No deadlocks when queue is empty
- [ ] `uv run pytest tests/test_broker_scheduler.py -q` green
- [ ] Full suite + ruff + pyright + architecture guardrail green

---

## Dependency Graph

```
TASK-5-1 (eval schema)
    │
    ▼
TASK-5-2 (eval runner)    TASK-5-3 (chat save/load)    TASK-5-4 (jail hook)    TASK-5-5 (broker scheduler)
                                                                                    
    (2 depends on 1)        (independent)                (independent)            (independent)
```

TASK-5-1 and TASK-5-2 have a soft dependency: TASK-5-2 imports the schema
classes from TASK-5-1. They can start simultaneously if TASK-5-1 publishes the
`EvalTask`/`EvalResult` dataclass definitions early (even before the YAML task
files exist). TASK-5-2 codes against the class definitions, not the task files.

Tasks 5-3, 5-4, and 5-5 share no files with any other task. They can run in
full parallel.

---

## Post-Phase Integration

After all five tasks merge to `main`:

1. **Wire the jail hook into the chat session** — pass `agent_id` from the
   session through the groom pipeline to the jail stage.
2. **Run the eval set against `main`** — establish the baseline. Every future
   change is measured against this baseline.
3. **Enable the self-evolving proposer** — with the eval harness in place,
   the correction detector's output finally has somewhere to go. The proposer
   stub  graduates from stub to real.

---

*End of Phase 5 development plan. Agents: read your task, claim it, stay in
your jail. The file is the law until the code enforces it.*
