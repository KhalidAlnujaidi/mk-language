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
~80–90% of the time — and prove it doesn't first.** Search the web and package
indexes; clone promising repositories into a temporary scratch folder and harvest
what fits (adopt, depend on, or vendor a piece); build from scratch only as a last
resort, and when you do, state what you searched and why nothing fit.

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

## The kernel rule

The kernel (`kernel/`) is pure, dependency-light, agent-agnostic, and 100%
tested. It **imports nothing from `products/` or `adapters/`**. This is enforced
mechanically by `tests/test_architecture.py` so that extracting the kernel into a
versioned package is always a mechanical step.

---

## Alignment with the workstation requirement

kinox embodies the machine-wide rule from `PROJECT-ALIGNMENT-REQUIREMENT.md`:
**one specialized model per task, never a general-purpose model multitasking; one
heavy GPU model resident at a time (offload barrier between stages); `uv` for
tooling.** The broker (Model Control Plane) is that rule made executable.
