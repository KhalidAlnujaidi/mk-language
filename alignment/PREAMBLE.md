# kinox — agent preamble

> **Canonical context injected at session start.** Each fact appears exactly once.
> Deeper detail lives in the source files (CONSTITUTION.md, vision.md, BRAIN.md)
> and can be read on demand — this is the lean summary, not a substitute.

## What kinox is

A **local-first, governed, cost-efficient workspace for running coding agents.**
Cheap local intelligence does groundwork; expensive frontier models do only the
high-value reasoning; everything an agent does is observable, reversible, and
fails in a known direction.

## Rule Zero — search and reuse before you build

Before writing any non-trivial component, assume it already exists (~80–90% of
the time) and prove it doesn't first. Search broadly (web, packages, skills, MCP
servers); clone and harvest; build only as last resort. **Exception:** the kernel
stays dependency-light — reuse there means vendoring a minimal piece.

## The three theses (design decisions must trace to these)

1. **Asymmetry** — ground truth beats the model. Deterministic code handles
   anything with a ground truth (regex, AST, git, fs); the model is called only
   for the genuinely fuzzy part, and the smallest model that fits.
2. **Fail-direction is per-component** — a guard fails **closed** (deny on doubt);
   an optimizer fails **soft** (pass through). Declared per gate, never global.
3. **Next-turn correction is a free quality label** — when a human re-does what
   the agent just did, that diff is training signal. Capture structurally, feed
   through an eval harness.

## Architecture map (key files)

| Concern | File · symbol |
|---|---|
| Agent loop (the harness) | `products/agent/loop.py` · `run_agent()` |
| Agent tools | `products/agent/tools.py` · `default_registry()` |
| Brain (model selection) | `daemon/brain.py` · `brain_tier()` |
| Backend transport | `daemon/backends.py` · `make_dispatch()` |
| Fallback-chain executor | `daemon/exec.py` · `execute()` |
| Chat TUI (drives each turn) | `products/chat/app.py` |
| Kernel (pure contracts) | `kernel/` — imports nothing from products/adapters |
| Products (built on kernel) | `products/` — groom, agent, chat, evolve, beacon |
| Adapters (agent wiring) | `adapters/` — e.g. `claude_code.py` |

**Kernel rule:** `kernel/` is pure, dependency-light, 100% tested, and imports
nothing from `products/` or `adapters/` — enforced by `tests/test_architecture.py`.

## Dev conventions (non-negotiable)

- **TDD** — tests first for any kernel/product/adapter logic.
- **uv** for everything: `uv run pytest`, `uv run ruff check`, `uv run pyright`.
- **Honest observability** — exact where measurable; labeled estimates otherwise.
- **`null`, never a fabricated `false`** — a missing capability is unknown.
- Branded/NewType pipeline types so a raw prompt can't reach the executor.
- Every gate declares its `fail_direction` (closed | soft).
