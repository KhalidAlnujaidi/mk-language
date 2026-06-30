# kinox — framework internals

> **Framework-scope context** (you are working *on* kinox itself). The operating
> axioms are injected separately (and apply here too); this file adds what only a
> framework-scope agent should know — kinox's own structure. A **project** session
> never sees this section.

## What kinox is

A **local-first, governed, cost-efficient workspace for running coding agents.**
Cheap local intelligence does groundwork; expensive frontier models do only the
high-value reasoning; everything an agent does is observable, reversible, and
fails in a known direction.

## Architecture map (key files)

| Concern | File · symbol |
|---|---|
| Agent loop (the harness) | `products/agent/loop.py` · `run_agent()` |
| Agent tools | `products/agent/tools.py` · `default_registry()` |
| Parallel fan-out (no overlap) | `products/agent/coordinator.py` · `run_parallel()` |
| Brain (model selection) | `daemon/brain.py` · `brain_tier()` |
| Backend transport | `daemon/backends.py` · `make_dispatch()` |
| Fallback-chain executor | `daemon/exec.py` · `execute()` |
| Chat TUI (drives each turn) | `products/chat/app.py` |
| Kernel (pure contracts) | `kernel/` — imports nothing from products/adapters |
| Products (built on kernel) | `products/` — groom, agent, chat, evolve, beacon |
| Adapters (agent wiring) | `adapters/` — e.g. `claude_code.py` |

**Kernel rule:** `kernel/` is pure, dependency-light, 100% tested, and imports
nothing from `products/` or `adapters/` — enforced by `tests/test_architecture.py`.

## Building kinox (non-negotiable)

- **TDD** — tests first for any kernel/product/adapter logic.
- **uv** for everything: `uv run pytest`, `uv run ruff check`, `uv run pyright`.
- Branded/NewType pipeline types so a raw prompt can't reach the executor.
- Every gate declares its `fail_direction` (closed | soft).
- Deeper detail on demand: `CONSTITUTION.md` (immutable core), `vision.md`, `BRAIN.md`.
