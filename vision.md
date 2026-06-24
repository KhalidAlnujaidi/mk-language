# kinox — Vision

> A local-first, governed, cost-efficient workspace for running coding agents.
> Cheap local intelligence does the groundwork; expensive frontier models do
> only the high-value reasoning; everything an agent does is observable,
> reversible, and fails in a known direction.

This document is the foundation. It states *what* we are building and *why* the
shape is the way it is. Implementation detail lives in `docs/` and the code; this
file changes rarely and on purpose.

---

## 0. Rule Zero — search and reuse before you build

**Before writing any non-trivial component, assume it already exists — it does
~80–90% of the time — and prove it doesn't before building it yourself.** This is
the precondition for everything below.

*The belief:* everything you need has almost certainly already been written and
released. The job is to find it and put the pieces together — composition over
creation, assembled from the ground up — not to invent.

1. **Search first, broadly** — web + package indexes (PyPI, crates.io, npm) +
   **agent skills/plugins** + **MCP servers** + existing tools. A whole MCP
   server or published skill can do an entire subsystem; prefer reusing one over
   writing code at all.
2. **Clone and harvest** — make a temporary scratch folder (e.g.
   `/tmp/scout-<task>/`), clone the promising repos into it, and take what fits
   (adopt, depend on, install a skill/MCP server, or vendor a piece) instead of
   regenerating it.
3. **Build only as the last resort**, and when you do, **state what you searched
   (web, packages, skills, MCP servers) and why nothing fit.** "I assumed nothing
   existed" is not a valid reason.

The one honest exception is the **kernel** (§4): it stays dependency-light, so
reuse there means vendoring a minimal piece or pushing the dependency to an outer
layer (`daemon/`, `products/`, `adapters/`) — never adding a runtime dep to the
pure core. Reuse-first still governs *which* outside thing you reach for.

---

## 1. What this is

`kinox` is a single system that sits between a human, a coding agent, and the
local machine. It does three things:

1. **Grooms the input** before the expensive agent ever sees it — redact secrets,
   expand shorthand, attach the right context, tag intent. Cheap and local.
2. **Governs the agent at runtime** — fail-closed guards, protected files, a
   VRAM-aware local-model broker, one model per task, an auditable action log.
3. **Shapes the output and the loop** — review diffs with cheap models, harvest
   the user's next-turn correction as a free quality label, and (carefully)
   evolve the system from that signal.

It is **single-machine first**, fleet-optional. It is **not** a sandbox or a VM —
it is defense-in-depth with honest limits and an easy recovery path.

---

## 2. Origin: three altitudes, one idea

`kinox` is the convergence of three prior rewrites of the same instinct. They
differ only in altitude:

| Project | Altitude | Governs |
|---|---|---|
| **squire** | the prompt | input grooming — the most portable slice |
| **kniox** | the agent | the agent's actions and resources, in userspace |
| **kinox** | the machine | "model as the shell," generative render-only output |

The arc went **grand → shippable**: full-OS ambition, down to userspace
governance, down to one sharp hook. The important discovery is that all three
roadmaps point back at the same primitives — `squire`'s report-back hook and
`kniox`'s corpus capture are the same idea; `squire`'s `fit.py`, `kniox`'s
manifest/dispatch, and `kinox`'s `model_select` are the same idea. We have been
circling a convergence point. This document names it.

---

## 3. North-star theses

Three ideas everything else is built around. If a design decision contradicts one
of these, the decision is wrong.

1. **Asymmetry — ground truth beats the model.** If a task has a ground truth
   (regex, AST, git, filesystem), plain deterministic code does it. A model is
   called *only* for the genuinely fuzzy part, and then the smallest model that
   fits. Cost discipline is structural, not aspirational.

2. **Fail-direction is per-component.** A guard fails **closed** (deny on doubt);
   an optimizer fails **soft** (pass through on doubt). This is a first-class
   property of every gate, declared per component — never a global default.

3. **The user's next-turn correction is a free quality label.** When a human
   immediately re-does what the agent just did, that diff is the highest-value
   training signal in the system. Capture it structurally (prior output hash,
   correction type, diff) and feed it through an eval harness — never apply it
   blindly.

---

## 4. The immutable kernel — six primitives

These six survived all three rewrites, each time more battle-tested. They are the
kernel. The kernel is pure, dependency-light, agent-agnostic, and 100% tested. It
**imports nothing from products or adapters** — enforced by a single import-lint
test so that extraction into a versioned package is always mechanical.

1. **Capability manifest** — detect, never assume. A missing capability is
   recorded as `null` (unknown), never a fabricated `false` (verified-absent) or
   assumed `true`. Models declare capabilities; the broker verifies with a canary
   task on registration. Liars get quarantined.

2. **Asymmetric router** — `route(task) → tier` over two axes: determinism
   (ground-truth vs fuzzy) and location (local rung vs cloud tier). Routing is a
   function of `TaskKind + length estimate + required capabilities`, not a
   free-form classifier — so it is auditable and testable.

3. **Policy gate with explicit fail-direction** — `propose → confirm → cancel`,
   conservative affirmative-detection, with fail-direction as a per-gate
   parameter (see thesis #2).

4. **Execution boundary** — a pure, unit-testable argv builder + a capability
   probe + actionable hints (the `bwrap` recipe). Policy is separated from
   effect so the policy can be tested without running anything.

5. **Working memory + corpus** — `next.md` / `CONSTITUTION.md` / boundaries, the
   brainstorm → spec → plan → TDD flow, and an append-only, secret-scrubbed
   session log. Both prior roadmaps independently reinvented this.

6. **Honest observability** — exact where we can measure, **labeled estimates**
   where we can't (e.g. local token counts are exact from Ollama; cloud counts
   are estimates and are never claimed as exact). One `EventRecord` per boundary.

The load-bearing contracts (`Task`, `Tier`, `Annotation`, `EventRecord`,
`FailDirection`, `Determinism`) are where the kernel earns its keep. Two of them —
`correction_of` (thesis #3) and `FailDirection` (thesis #2) — fell directly out of
comparing the three repos and must exist from commit one.

---

## 5. Architecture

### 5.1 Two planes, one contract

The single most important structural decision: there are **two stacks**, and the
boundary between them is explicit, not fuzzy.

- **ML governance plane (Python).** `squire` + broker + hooks + daemon. Owns
  model lifecycle, input grooming, action logging, rail enforcement. `uv` +
  FastAPI + Typer.
- **Business application plane (optional, TypeScript/NestJS).** A modular
  monolith for any domain logic built *on top of* the workspace. Owns domain
  rules, persistence, transport.
- **The contract between them is the OpenAI-compatible HTTP API + a typed SDK.
  Nothing else.** The business app never imports Python; the Python plane never
  knows about domain modules. This is Ports & Adapters lifted one level up.

> Note: the business plane is a *possible* consumer, not a launch requirement.
> The governance plane is the product. Don't build the monolith until a real
> domain needs it.

### 5.2 Layers

- **Layer 0 — Host & setup.** Idempotent one-liner `install.sh`; `kx setup`
  detects hardware (CPU/GPU/VRAM, backends) into a manifest; `kx` symlinked as
  the entrypoint.
- **Layer 1 — Input grooming (`squire`).** Default `UserPromptSubmit` hook.
  Stages: redact → expand → context → tag. Deterministic stages first; exactly
  **one** capped local-model call for the fuzzy tag step. Fail-soft, bypass
  prefix, JSONL logging.
- **Layer 2 — Runtime governance & broker (`kniox`).** `kx` launcher injects
  alignment + context into a guarded session; fail-closed guard hooks; the
  **Model Control Plane** broker daemon (below); project scaffolding under
  `~/kinox/projects/<name>/`.
- **Layer 3 — UX (`kinox` vision).** Voice input (Whisper → grooming pipeline),
  generative/TUI output, post-session review loop routing diffs to cheap
  reviewers. Forward-looking; stubbed early.
- **Cross-cutting — Alignment & observability.** Central alignment contracts
  imported everywhere; per-project `next.md` (size-capped to prevent bloat);
  one `EventRecord` per boundary; a dashboard over the logs.

### 5.3 The broker (Model Control Plane)

A Python/FastAPI daemon that turns "one model per task" into reality on
constrained hardware:

- **Registry** — per-model metadata (backend, size, capabilities, `preferred_for`,
  VRAM estimate, observed fitness scores).
- **Resource monitor** — VRAM/CPU/RAM via `nvidia-smi`/`pynvml`/`psutil`; tracks
  loaded models + KV-cache footprint.
- **Router/dispatcher** — heuristic classifier → score candidates (availability,
  VRAM fit, capability match, latency) → select → fallback chain
  (specific → general local → smaller quant → CPU).
- **Backend adapters** — Ollama (default), vLLM, llama.cpp; unified
  OpenAI-compatible output.
- **Scheduling** — async queue, per-GPU concurrency limits, priority (grooming/
  review high, long sessions low). `warm_set_size` is a **function of available
  VRAM**, not a static config, and auto-tunes down on observed OOM.
- **API** — OpenAI-compatible `/v1/chat/completions` plus `/broker/status`,
  `/broker/route` (debug), `/broker/models`. Bind to a **Unix domain socket**,
  not TCP loopback, to kill latency and local attack surface.
- **Observability** — structured JSONL (`task_id`, `model_used`, latency, tokens,
  VRAM delta), exported under a single trace context.

### 5.4 The ground-truth taxonomy (makes routing executable)

```
DETERMINISTIC  (regex/AST/git/fs)              → no model, plain code
STRUCTURED     (NER, classification, JSON)     → small local model, grammar-constrained
FUZZY          (intent, expansion, summary)    → small local model, capped tokens
REASONING      (codegen, review, planning)     → broker picks a reasoning-tier model
```

---

## 6. Self-healing and self-evolving (governed)

The system should get cheaper, more reliable, and more aligned with use — **without
full autonomy**. Two layers, both gated.

- **Self-healing (reactive).** Watchdog + heartbeat with backoff restart; resource
  guardian that unloads least-used models / downgrades quant / spills to CPU under
  OOM risk; per-task retry + circuit-breaker fallback chains; session
  snapshot/rollback of protected files; `kx doctor --auto-fix` reconciling
  manifest vs. runtime.
- **Self-evolving (proactive).** A meta-review cycle — *observe* (aggregate logs +
  corrections) → *analyze* (cheap local reviewer, capped frontier) → *propose*
  (prompt tweaks, new groom stage, router-score change) → *validate* (eval set) →
  *gate* (human approval for anything touching code; auto-merge only for
  prompt/config inside a sanctioned schema). Proposals are git branches +
  eval diffs stored in `evolutions/`.

> Inspirations (EvoAgentX: TextGrad / AFlow / MIPRO; light EvoAgent-style
> population of 4–8 prompt/hook variants) are *references*, not dependencies. We
> build a bespoke, lightweight loop — and only after §8.3 exists.

---

## 7. Hard truths — what we refuse to pretend

These are the non-negotiable honesty constraints. They override enthusiasm.

1. **Hooks are a speed bump, not a wall.** `--dangerously-skip-permissions`
   bypasses them. Real protection for `next.md` / `alignment/` needs OS-level
   enforcement (`chattr +i`, a separate uid with read-only mounts, documented
   recovery path). If we won't do OS enforcement, the docs **must** say the rails
   are advisory, not enforced. No false expectations.

2. **Self-evolving without an eval harness is just drift.** You cannot evolve what
   you cannot measure. No self-evolving code ships before §8.3 exists.

3. **One trace, not two ID systems.** A single OpenTelemetry trace context
   propagates squire-hook → HTTP → broker → inference → tool call → file edit.
   The trace ID *is* the correlation ID.

4. **The agent outbox is one structure that pays three ways.** Every intended file
   edit / shell command / tool call is written to a durable log *before* execution.
   On crash it is the replay source; on success it is the audit trail; on
   correction it is the free quality label. Crash-recovery, audit, and RLHF signal
   from one log.

---

## 8. Build strategy — bullet-proof start

Deliberately slow at first, then very fast, because the kernel is solid and drift
is caught immediately.

### 8.1 Day 1 (non-negotiable)
- Repo `kinox`, protected `main`, PRs even solo.
- Hermetic Python via `uv`; strict `pyproject.toml` (Python 3.11+, ruff, pyright,
  pytest).
- **Architecture guardrail from commit #1:** `test_architecture.py` enforces
  "`kernel/` imports nothing from `products/` or `adapters/`."
- `kx doctor` stub as a pre-commit hook; protected-file checksums.

### 8.2 M0 — the smallest thing that is real
Small enough to finish; big enough to force every kernel contract to be honest.

- `kernel/manifest.py` — probe machine, list available tiers (which local rung
  fits + cloud iff a key exists). `null`, never zero.
- `kernel/router.py` — ground-truth → deterministic; the one `tag` task → smallest
  fitting model.
- `kernel/metrics.py` + `EventRecord` — append-only, exact local counts,
  `correction_of` slot present from commit one.
- `products/groom/pipeline.py` — redact → expand → context → tag.
- `adapters/claude_code.py` — the `UserPromptSubmit` hook adapter.
- **Correction detector** — next prompt short + starts with "no/actually/I meant"
  → mark prior `EventRecord` corrected. Heuristic now, model-scored later. This is
  nearly free and it is the compounding moat — it ships in M0, not "someday."

First three commands: `kx` (banner + menu), `kx doctor` (health), `kx new
<project>` (scaffold `next.md` + register hooks). **Build the scaffold path first** —
if a new module can't be scaffolded in ~10 seconds, the architecture won't survive
deadlines.

### 8.3 Before any self-evolving code
- A **golden eval set**: 20–50 tasks with *behavioral* assertions ("did it redact
  the secret?", "did it route to the cheap model?", "did it refuse the destructive
  command?") — not exact-output matching.
- A **regression runner** that runs the set against any proposed change.
- A **versioned artifact store**: every evolution = branch + eval diff; merge
  requires eval pass + human approval for code.

### 8.4 Reference skeleton

```
kinox/
├── install.sh · kx                 # one-liner setup + entrypoint
├── pyproject.toml                  # uv + strict tooling
├── alignment/                      # CONSTITUTION.md — the three theses, immutable
├── kernel/                         # the constant: contracts, manifest, router,
│                                   #   gate, metrics, memory, sandbox (100% tested)
├── products/groom/                 # first product: the squire pipeline
│   ├── stages/                     # redact · expand · context · fingerprint
│   ├── tag.py                      # the ONE fuzzy step → router → smallest model
│   └── pipeline.py
├── adapters/claude_code.py         # the agent hook adapter
├── daemon/                         # MCP broker (start minimal)
├── projects/                       # user projects (gitignored)
├── docs/  ·  tests/  ·  .github/workflows/
```

---

## 9. Quick wins, ranked by ROI

The highest-leverage early work, roughly in order:

| # | Win | Effort | Impact |
|---|---|---|---|
| 1 | Next-turn feedback loop (capture correction → JSONL → nightly cheap reviewer) | very low | very high |
| 2 | Model fitness scoring (router uses `fitness × speed × vram_fit`, not static rules) | low | high |
| 3 | Config-driven preprocessor stages (declarative `config.toml`, reorderable) | low | high |
| 4 | `kx doctor --auto-fix` (hardware/registry/protected-file reconciliation) | low | high |
| 5 | Streamlit/TUI dashboard over the JSONL (stop flying blind) | medium | high |

Almost-free hygiene: every hook declares `fail_direction: closed | soft | ignore`;
exact + semantic cache (MD5 exact-match, tiny BGE-micro for fuzzy); git-diff +
ctags context pruning instead of whole files; temporal-decay file weighting
(`locality / Δt`) instead of vector search; per-session token budget with a
fail-soft early exit; branded/`NewType` pipeline types so a raw prompt can't reach
the executor.

---

## 10. Open decisions

- **Name.** Working name `kinox`; alternates floated: `lumen`, `nexus`, `axiom`.
  (`kin` is reserved as the admin/core scope and is blacklisted as a project name.)
- **Business-plane language.** Go vs TypeScript/NestJS. Lean TS/NestJS for feature
  velocity, polymorphic data, and one language across CLI/hooks/server — but this
  only matters once there's a real domain to build. Deferred.
- **Monorepo vs. separate kernel package.** Start monorepo; the import-isolation
  rule makes later extraction mechanical, so there's no cost to waiting.
- **How agent-agnostic to commit now.** Emit a neutral `Annotation`, keep all
  agent-specific wiring in the one adapter — but don't write a second adapter
  until something actually needs it. Agent-agnostic is a *shape*, not a second
  integration.

---

*This vision is the spine. Everything built should trace back to one of the three
theses (§3) and respect the four hard truths (§7). When something here turns out
to be wrong, change this file deliberately and say why.*
