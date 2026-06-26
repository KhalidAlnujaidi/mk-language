# kinox · BRAIN & AGENT HARNESS

> **What runs the "agent" / the "brain", and where.** This file is the admin map:
> when you type into a `kx` session, this is the exact chain of files that turns
> your message into a tool-using agent turn. Kept at the repo root on purpose.

## TL;DR — the one harness that runs the agent

| Role | File · symbol |
|---|---|
| **THE agent harness** (the loop) | **`products/agent/loop.py` · `run_agent()`** |
| The agent's tools (hands/eyes) | `products/agent/tools.py` · `default_registry()` |
| Which model *is* the brain | `daemon/brain.py` · `brain_tier()` / `brain_chain()` |
| Transport to the model | `daemon/backends.py` · `make_dispatch()` |
| Fallback-chain executor | `daemon/exec.py` · `execute()` |
| The TUI that drives it each turn | `products/chat/app.py` · `_run_agent_turn()` |
| Entry point (loads secrets) | `kx` · `_load_env()` → reads `~/.kinox/env` |

**The agent loop is `products/agent/loop.py:run_agent`.** Everything else feeds it:
`brain.py` picks the model, `backends.py` reaches it, `tools.py` gives it hands,
`exec.py` walks the fallback chain, `app.py` renders the turn.

## The brain (which model thinks)

- **Default: `glm-5.2` on z.ai (cloud)**, via the GLM **Coding Plan** endpoint
  `https://api.z.ai/api/coding/paas/v4` — resolved in `daemon/brain.py`.
- **Fallback: the first local Ollama model** (e.g. `deepseek-r1:8b`). The chain is
  always `[cloud brain, local]` — a cloud outage/missing key fails **soft** to
  local (vision §3 thesis #1 + §7 fail-soft).
- **Selectable** at runtime from chat: `/model` (z.ai presets), `/model openrouter
  <id>` (any OpenRouter text model), `/model local`. `/models` lists OpenRouter
  text→text ids. A choice is applied live (next turn) and persisted to
  `~/.kinox/env` via `brain.py:set_brain()`.
- **Override via env** (read every turn): `KINOX_BRAIN` (model, or `local` to
  disable cloud), `KINOX_BRAIN_BACKEND` (`zai` | `openrouter` | `ollama` | …),
  `KINOX_BRAIN_WHERE` (`cloud` | `local`). Keys: `ZAI_API_KEY`,
  `OPENROUTER_API_KEY` — in `~/.kinox/env`, never committed.

## The agent (how a turn runs)

Every message in a `kx` session is an **agent turn** (not plain chat):
`products/chat/app.py:_run_agent_turn()` builds the **unrestricted** toolset and
calls `run_agent()`.

```
you type in a kx session
        │
        ▼
products/chat/app.py · _pt_loop / _text_loop      (every turn → agent)
        │
        ▼
products/chat/app.py · _run_agent_turn()
        │   • brain  = daemon/brain.py · brain_tier(fallback=local)
        │   • tools  = products/agent/tools.py · default_registry(
        │                 allow_bash=True, allow_write=True)   ← NO restrictions
        ▼
products/agent/loop.py · run_agent()              ◀── THE AGENT HARNESS
        │   Perceive → Decide → Act → Observe, up to 30 turns
        ▼
daemon/exec.py · execute([brain, local], …)       fallback chain, fail-soft
        │
        ▼
daemon/backends.py · make_dispatch()              OpenAI-compatible HTTP
        │
        ▼
the model (z.ai glm-5.2 / OpenRouter / local Ollama)
```

### Tools the agent has (unrestricted, in-scope)

From `products/agent/tools.py` via `default_registry(root, skills=…,
allow_bash=True, allow_write=True)`:

- `read_file`, `list_dir` — read the scope (sandboxed to the session root).
- `write_file` — create/overwrite files in the scope.
- `run_bash` — run any shell command in the scope (full read/write/exec).
- `find_skill`, `load_skill` — the `.claude/skills` corpus (~275 skills).

`kx` sessions run with **write + bash ON and no pre-tool guard** — a fully-trusted
operator agent. The `_within()` guard still fails **closed** outside the session
root; `run_bash` is the deliberate escape hatch beyond it. (Other callers of
`default_registry`, e.g. the beacon loop, keep the fail-closed default: write/bash
**off**.)

## Not the agent

- `products/chat/session.py · ChatSession.send()` — **plain chat**, no tools.
  Reachable only via the `/chat <msg>` escape command. Used for cheap one-off
  replies; it is *not* the agent path.
- `products/agent/tools.py` ToolRegistry guard / `run_agent(guard=…)` — the
  fail-closed pre-tool gate. `kx` sessions pass **no** guard (unrestricted); other
  embeddings can pass one.

## Related

- Brain rationale & theses: [`vision.md`](vision.md) §3–§5,
  [`alignment/CONSTITUTION.md`](alignment/CONSTITUTION.md).
- The 24/7 self-development agent (separate harness): `products/beacon/harness.py`
  drives `run_agent()` too, but as the evolve **proposer** (cluster/local model),
  with the cheap local model as verifier.
