# Ralph Loop — kinox multi-goal session

Work the goals below **top-down, one at a time**. For each goal: build in small
TDD increments (test first, watch it fail, minimal code, green), commit each
green step, and when the goal's acceptance criteria are all met AND
`uv run pytest -q` + `uv run ruff check .` + `uv run pyright` are ALL green,
merge the goal's branch into `main` with `--no-ff`, then move to the next goal.

Output the completion promise EXACTLY when ALL FOUR goals are merged to `main`
and `main` is fully green.

## Working discipline (per goal)
- Branch per goal off `main`: `git checkout -b goal-<n>-<slug> main`.
- TDD: no production code without a failing test first (the iron law).
- Green gates before any "done" claim: pytest + ruff + pyright, plus
  `tests/test_architecture.py` (kernel purity) stays green.
- Merge to `main` with `--no-ff` when the goal is green; do NOT push to origin.
- Update this file's checkboxes and the handoff (`~/.remember/remember.md`) as
  goals land.

## Binding constraints (all goals)
- `kernel/` stays stdlib-only and imports nothing from products/adapters/
  daemon/evals — enforced by `tests/test_architecture.py`.
- **Rule Zero**: search web/PyPI/skills/MCP and REUSE before building. For these
  goals specifically: resource monitor → reuse `psutil` / `pynvml` / `nvidia-smi`
  (don't hand-parse); dashboard → reuse Streamlit or a TUI lib (textual/rich),
  don't hand-roll a renderer. Add deps via `uv add` (outer layers only).
- Honest observability: `null` for unknown, never a fabricated `false`/`0`;
  never claim a cloud token count is exact.
- Do NOT re-summon vast.ai GPUs — build locally on the A4500.
- Specialized-one-model-per-task and the existing kernel contracts are law.

---

## GOAL 1 — M1 broker depth (vision §5.3)  [x] DONE (merged to main)
Brick 1 is just the FastAPI surface + a route/fallback skeleton. Deepen it:
- **Registry**: per-model metadata (backend, size, capabilities, `preferred_for`,
  VRAM estimate, observed fitness). Verify a model's declared capabilities with a
  **canary task on registration**; quarantine liars (vision §4.1).
- **Resource monitor**: live VRAM/CPU/RAM (reuse psutil/pynvml/nvidia-smi);
  `null` when unmeasurable. Tracks loaded models + KV-cache footprint best-effort.
- **Scoring router/dispatcher**: score candidates by availability × VRAM-fit ×
  capability-match × latency; select; then the fallback chain
  (specific → general local → smaller quant → CPU).
- **/broker/status** enriched with registry + live resource snapshot.
Acceptance: TDD tests for registry+canary, resource monitor (mocked probes →
null-honesty), scoring order, and fallback ordering; all green.

## GOAL 2 — Next-turn feedback loop (vision §9 #1, thesis #3)  [x] DONE
The compounding moat. The detector (`kernel.corrections.looks_like_correction`)
exists; wire it end-to-end:
- In the adapter/groom path, when the next prompt looks like a correction of the
  prior, emit an `EventRecord.as_correction_of(prior_task_id)` to the metrics
  sink (capture prior-output hash + correction type + diff where available).
- A cheap-reviewer **stub** that reads correction EventRecords and emits a
  structured "what to review" record (no model call required for the stub).
Acceptance: TDD tests proving a correction turn marks the prior task corrected
in the JSONL, and the reviewer stub aggregates corrections; all green.

## GOAL 3 — Self-healing + kx doctor (vision §6 reactive, §9 #4)  [ ]
- **Watchdog/heartbeat** with backoff restart for the broker daemon (pure,
  unit-testable backoff policy + a thin supervisor).
- **Resource guardian**: under OOM risk, unload least-recently-used model /
  downgrade quant / spill to CPU — reuse GOAL 1's resource monitor.
- **`kx doctor --auto-fix`**: reconcile manifest vs runtime (missing model,
  stale registry, protected-file checksum drift) and report/fix.
Acceptance: TDD tests for backoff policy, LRU-unload decision, and doctor
reconciliation (pure decision functions, no real processes killed in tests);
all green.

## GOAL 4 — Observability dashboard (vision §9 #5)  [ ]
A view over the EventRecord JSONL + `/broker/status` so we stop flying blind:
per-task model, latency, tokens (labeled exact/estimate), correction rate,
fallback frequency. Reuse Streamlit or a TUI lib (Rule Zero) — do not hand-roll.
Keep the data-shaping logic pure + unit-tested; the UI is a thin shell.
Acceptance: TDD tests for the pure aggregation functions (counts, rates,
per-model rollups) over a synthetic JSONL; the UI launches; all green.

---

Completion promise token: KINOX_GOALS_ALL_MET
