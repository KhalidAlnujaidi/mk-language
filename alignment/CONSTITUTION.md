# CONSTITUTION

_The immutable core of kinox. This file changes rarely and on purpose. Every
design decision must trace back to a thesis below and respect every hard truth.
If a decision contradicts one of these, the decision is wrong._

---

## Rule Zero — search and reuse before you build

_Added 2026-06-22 (deliberate change): the strongest cost-and-quality lever is not
writing code that already exists. This sits above the three theses because it
governs whether we build at all._

**Before writing any non-trivial component, assume it already exists — it does
~80–90% of the time — and prove it doesn't first.** The belief underneath this:
everything you need has almost certainly already been written and released; the
job is to find it and assemble the pieces, not to invent — composition over
creation. Search broadly — the web, package indexes, **Claude Code skills/plugins,
and MCP servers** (a whole MCP server or published skill can do an entire
subsystem for us); clone promising repositories into a temporary scratch folder
and harvest what fits (adopt, depend on, install, or vendor a piece); build from
scratch only as a last resort, and when you do, state what you searched and why
nothing fit.

The single exception is **the kernel rule below**: the kernel takes no runtime
dependency, so reuse there means vendoring a minimal piece or keeping the
integration in an outer layer — never adding a dep to the pure core. Reuse-first
still decides *what* you reach for.

---

## The three theses

1. **Asymmetry — ground truth beats the model.**
   If a task has a ground truth (regex, AST, git, filesystem), plain
   deterministic code does it. A model is called *only* for the genuinely fuzzy
   part, and then the smallest model that fits. Cost discipline is structural,
   not aspirational.

2. **Fail-direction is per-component.**
   A guard fails **closed** (deny on doubt); an optimizer fails **soft** (pass
   through on doubt). This is a first-class property of every gate, declared per
   component — never a global default.

3. **The user's next-turn correction is a free quality label.**
   When a human immediately re-does what the agent just did, that diff is the
   highest-value training signal in the system. Capture it structurally (prior
   output hash, correction type, diff) and feed it through an eval harness —
   never apply it blindly.

---

## The four hard truths (honesty constraints — they override enthusiasm)

1. **Hooks are a speed bump, not a wall.** `--dangerously-skip-permissions`
   bypasses them. Real protection for `next.md` / `alignment/` needs OS-level
   enforcement (`chattr +i`, a separate uid with read-only mounts, a documented
   recovery path). If we won't do OS enforcement, the docs **must** say the rails
   are advisory, not enforced. No false expectations.

2. **Self-evolving without an eval harness is just drift.** You cannot evolve
   what you cannot measure. No self-evolving code ships before the golden eval
   set + regression runner exist.

3. **One trace, not two ID systems.** A single trace context propagates
   groom-hook → HTTP → broker → inference → tool call → file edit. The trace ID
   *is* the correlation ID.

4. **The agent outbox is one structure that pays three ways.** Every intended
   file edit / shell command / tool call is written to a durable log *before*
   execution. On crash it is the replay source; on success it is the audit
   trail; on correction it is the free quality label.

---

## The parallelism axiom — agents are independent, never collapsed

_Added 2026-06-27 (deliberate change): the governed pipeline can fan one job out to
two or more agents at once. The moment work runs in parallel the failure mode is no
longer "too slow" — it is two agents quietly editing the same file and one silently
winning. This is an axiom, not a feature toggle: parallelism that cannot guarantee
non-overlap is forbidden._

**Parallel agents own disjoint slices of the work, and the boundary between slices
is enforced, not trusted.** Each agent may write only within the slice it owns; a
write — direct or through the shell — that reaches into another agent's slice is
refused (fail-CLOSED, thesis #2), and the coordinator proves the owned sets are
disjoint *before a single agent is spawned*. The consequence is the axiom itself:
**there is no work to collapse and none to override.** No agent's output can shadow
another's, and there is no master agent or human override that silently merges two
parallel results into one — a conflict surfaces as a refused action in the trace,
never as a lost edit. Reads may overlap freely (observing a file cannot override
it); only writes are partitioned. The mechanism is `products/agent/coordinator.py`
(`assert_disjoint` + `ownership_guard` + `run_parallel`).

---

## The scope axiom — framework and project, with a wall between them

_Added 2026-06-27 (deliberate change): there are exactly two scopes a session can
run in, and what each is allowed to know is a governance boundary, not a
convenience._

**A session is either framework scope (working *on* kinox) or project scope
(working *in* a user project), and a project is told only its axioms — never the
framework that runs it.** A framework session receives the axioms plus kinox's
internals (architecture map, file layout); a project session receives the
operating axioms alone (`alignment/AXIOMS.md`) and nothing about the framework's
structure, internals, or git state — it follows the rules pre-injected into it and
is otherwise unaware of the system hosting it. The wall is enforced three ways:
the **scope-aware preamble** (`environment.session_preamble`, the repo root is the
only framework scope; everything else is a project), the **root jail** that
confines every tool to its scope (fail-CLOSED), and **per-project isolation** —
every project is its own git repo with its own recoverable baseline (`kx new`
initializes it; `projects/` is never tracked by the framework repo). A project
cannot reach up into the framework, and the framework's self-knowledge never
leaks down into a project.

---

## The kernel rule

The kernel (`kernel/`) is pure, dependency-light, agent-agnostic, and 100%
tested. It **imports nothing from `products/` or `adapters/`**. This is enforced
mechanically by `tests/test_architecture.py` so that extracting the kernel into a
versioned package is always a mechanical step.

---

## The brain rule

_Added 2026-06-26 (deliberate change): names the model tiering every `kx` scope
obeys, so it is a framework property, not a per-session setting._

kinox's **brain** — the high-value *reasoning* tier — is **cloud-first, local
last**. This does not contradict thesis #1: the genuinely hard, fuzzy reasoning is
exactly where the best model earns its cost, while everything cheaper — grooming,
tagging, deterministic checks — stays local. The brain resolves through one
chokepoint (`daemon/brain.py:brain_chain`), so the route/hub, `kx kin` (admin),
`kx <project>`, and `kx dev` all inherit the same chain; **no scope can opt out.**

The chain, top to bottom, **fails soft** (thesis #2) — an outage, missing key, or
error at any tier degrades to the next, never offline:

1. **Primary — the frontier subscription brain.** `glm-5.2` on z.ai (cloud).
2. **Secondary — OpenRouter.** Provider-diverse cloud, and the experimentation
   surface for trying other models. Active only when `OPENROUTER_API_KEY` is set.
3. **Fallback — the smallest fitting local model.** Keeps the workspace usable
   with no network and no keys.

Only an empty chain (no cloud, no local) is a hard stop. Keys live in
`~/.kinox/env` (`ZAI_API_KEY`, `OPENROUTER_API_KEY`), never committed.

---

## Alignment with the workstation requirement

kinox embodies the machine-wide rule from `PROJECT-ALIGNMENT-REQUIREMENT.md`:
**one specialized model per task, never a general-purpose model multitasking; one
heavy GPU model resident at a time (offload barrier between stages); `uv` for
tooling.** The broker (Model Control Plane) is that rule made executable.
