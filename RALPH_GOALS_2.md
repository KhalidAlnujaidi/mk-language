# Ralph Loop — kinox session 2 (self-authored goals)

Work the goals below **top-down, one at a time**. For each: build in small TDD
increments (test first, watch it fail, minimal code, green), commit each green
step, and when the goal's acceptance criteria are met AND `uv run pytest -q` +
`uv run ruff check .` + `uv run pyright` are ALL green, merge the goal branch
into `main` with `--no-ff`, then move on.

Output the completion promise EXACTLY when ALL FOUR goals are merged to `main`
and `main` is fully green.

## Working discipline (per goal)
- Branch per goal off `main`: `git checkout -b g2-<n>-<slug> main`.
- TDD iron law: no production code without a failing test first.
- Green gates before any "done": pytest + ruff + pyright, plus
  `tests/test_architecture.py` (kernel purity) stays green.
- Merge to `main` with `--no-ff` when green; do NOT push to origin.
- Update this file's checkboxes + the handoff (`~/.remember/remember.md`).

## Binding constraints (all goals)
- `kernel/` stays stdlib-only, imports nothing from products/adapters/daemon/
  evals — enforced by `tests/test_architecture.py`.
- **Rule Zero**: search + REUSE before building (Typer for the CLI, stdlib
  `tomllib` for config, existing modules for everything else). Deps via
  `uv add` into the right extra; never into the kernel.
- Honest observability: `null` for unknown, never a fabricated `false`/`0`.
- Do NOT re-summon vast.ai GPUs — build locally on the A4500.
- The existing kernel contracts and the three theses are law.

---

## GOAL 1 — `kx` CLI surface  [x] DONE
Make the framework usable from one entrypoint. Reuse **Typer**. Commands:
- `kx doctor` — run `daemon.doctor.diagnose` over a best-effort
  expected-vs-present model set + protected-file checksums; print findings;
  `--auto-fix` applies only the fixable ones (report the rest).
- `kx status` — print the observability dashboard table
  (`products.dashboard.app.render` over the broker JSONL).
- `kx new <name>` — scaffold `projects/<name>/` with a size-capped `next.md`.
Acceptance: TDD tests for each command's pure core (a Typer `CliRunner` or the
underlying functions) — doctor formats findings, new scaffolds the dir, status
renders; all green. Keep I/O thin; logic testable.

## GOAL 2 — Config-driven groom stages (vision §9 #3)  [x] DONE
Make the groom pipeline declarative + reorderable instead of hard-coded.
- A `config.toml` schema (parsed with stdlib `tomllib`) listing stages in order
  with an `enabled` flag, e.g. `[[stage]] name="redact" enabled=true`.
- A pure loader → ordered list of enabled stage names, with a safe default when
  the file is absent/malformed (fail-soft) and validation that rejects unknown
  stage names.
Acceptance: TDD tests for parse/validate/default/reorder; an enabled=false stage
is skipped; unknown stage name is rejected; all green. (Wire into the pipeline
only as far as selecting the stage order — keep behavior backward-compatible.)

## GOAL 3 — Agent outbox (vision hard truth #4)  [x] DONE
One durable log that pays three ways. Every intended effect (file edit / shell
command / tool call) is written to an append-only outbox **before** execution.
- `OutboxEntry` (id, kind, payload, status: pending|done|failed) + an append-only
  `Outbox` store (JSONL) with `append`, `mark_done`, `mark_failed`, and
  `pending()` for crash replay.
Acceptance: TDD tests — append then mark_done round-trips; `pending()` returns
only unfinished entries (the crash-replay source); append-only (history never
rewritten); all green.

## GOAL 4 — Self-evolving proposer, GATED (vision §6 proactive)  [ ]
The capstone the §8.3 harness unlocks. A governed observe → propose → validate →
gate cycle (deterministic stub — NO live LLM, NO autonomous code merge):
- **observe**: aggregate corrections via `products.feedback.review`.
- **propose**: emit a `Proposal` (a config/prompt tweak within a sanctioned
  schema) targeting the most-corrected area — never a code edit.
- **validate**: run the golden eval set via `evals.runner.run_eval_set`; capture
  before/after into `evals.store.record_evolution`.
- **gate**: auto-approve ONLY sanctioned-config proposals whose eval stays green;
  anything touching code → `requires_human=True`, never auto-applied.
Acceptance: TDD tests — a green sanctioned-config proposal is auto-approved and
an evolution artifact is written; a code-touching proposal is gated
(`requires_human`); a proposal that regresses the eval set is rejected; all green.

---

Completion promise token: KINOX_GOALS2_ALL_MET
