# Working with kinox

This file is injected as alignment context for coding agents working *on* kinox
itself. (User projects get their own `next.md` under `projects/<name>/`.)

## What kinox is
A local-first, governed workspace for running coding agents. The spine lives in
`../vision.md`; the immutable core in `CONSTITUTION.md`. Read both before
proposing structural changes.

## Layout (vision §8.4)
- `kernel/`   — pure contracts + core logic. Imports nothing from products/adapters.
- `products/` — built on the kernel. First product: `groom/` (the squire pipeline).
- `adapters/` — agent-specific wiring. `claude_code.py` is the *only* Claude-specific file.
- `daemon/`   — the Model Control Plane broker (start minimal).
- `alignment/`— this file + CONSTITUTION.md (immutable core).
- `projects/` — user projects (gitignored).

## How we build (non-negotiable)
- **TDD.** Tests first, for any kernel/product/adapter logic.
- **uv** for everything: `uv run pytest`, `uv run ruff check`, `uv run pyright`.
- **The architecture guardrail** (`tests/test_architecture.py`) must stay green.
- **Honest observability.** Exact where measurable; labeled estimates otherwise.
  Never claim a cloud token count is exact.
- **`null`, never a fabricated `false`.** A missing capability is unknown, not
  verified-absent.

## Conventions
- `kin` is the reserved admin/core scope — blacklisted as a project name.
- Branded/`NewType` pipeline types so a raw prompt can't reach the executor.
- Every gate declares its `fail_direction` (closed | soft).
