# v03 plan — the MK language as a layered NL→executable translator

> **Purpose (unchanged, sharpened):** MK is a *one-to-one translator* — it takes
> English intent and turns it into **computationally executable commands**, then runs
> them and verifies the outcome. v01/v02 proved this for 11 direct OS operations.
> v03 generalizes it into a **layered** system so the *same* intent can target
> different execution surfaces (terminal, Python, …) — "the miniature levels where
> things get interesting."

## 0. The core reframe — one graph, many targets

v02 today: `English intent → interpreter → OS call` (direct, hard-wired, one target).

v03: insert the intermediate layer the cheat code (AIOS+CoRE) already mandates —

```
English intent
   │  parse (CoRE 4-field step: Name ::: Type ::: Instruction ::: Connection)
   ▼
ASG  — Abstract Syntax Graph: a target-INDEPENDENT logic/data-flow graph
   │  validate (typed, sandboxed, fail-closed on irreversible)
   ▼
┌─────────────┬─────────────┬─────────────┐   ← the "miniature levels":
│ terminal    │ python      │ (future:    │     pluggable code-generators,
│ backend     │ backend     │  sql/http…) │     each compiled FROM the same ASG
└─────────────┴─────────────┴─────────────┘
   │  execute in sandbox
   ▼
verified OS outcome  (ground truth beats model — done = it RUNS)
```

The ASG is the whole point: **never translate English straight to a code string.**
Translate English → graph (once), then each backend is a small, independently
testable compiler from graph → its surface. Add a new "level" = add one backend, no
change to the parser or the other levels.

## 1. What the council builds in v03 (the components)

1. **Parser** `NL → ASG` — adopt CoRE's structured-intent unit
   (`Step Name ::: Step Type ::: Step Instruction ::: Step Connection`, Type ∈
   {Process, Decision, Terminal}). Control flow falls out of `Connection`
   (Sequence / Selection / Iteration).
2. **ASG + validator** — typed nodes behind AIOS-style "managers"; the **Access
   Manager** rule survives from v02: irreversible ops (delete/overwrite) fail
   CLOSED unless confirmed.
3. **Backends (the levels)** — `ASG → terminal`, `ASG → python`. Each is a separate
   conformance-gated module.
4. **Executor + sandbox** — run the generated artifact in a temp dir, no network, no
   host mutation (v02's sandbox pattern, reused).

## 2. Phased build order (each phase = a new conformance suite, memory carried)

- **Phase A — introduce the ASG (enabling move).** Refactor v02's direct interpreter
  to `parse → ASG → execute`, keeping the **existing 11/11 green** the whole way. No
  new capability; this is the load-bearing refactor. Done = 11/11 still pass *through
  the graph*.
- **Phase B — terminal backend.** `ASG → shell`. New rungs are NL intents whose
  expected outcome is produced by the *generated shell command* (e.g. "list the txt
  files in logs, newest first" → a `ls`/`find` pipeline → expected listing). Reuse
  the 11 intents as the first terminal rungs, then add terminal-native ones (pipes,
  globs, `wc`, `grep`).
- **Phase C — python backend.** `ASG → python`. Same intents, now compiled to Python
  that produces the expected output. This is where "another layer for Python
  encoding" lands. Adds compute rungs the shell is awkward at (parse/transform/count
  with logic).
- **Phase D — cross-target invariant.** The determinism axiom as a *test*: the same
  intent through the terminal backend and the python backend must yield the **same
  OS outcome**. This is the proof that the ASG is genuinely target-independent.

Each phase keeps the v01/v02 → v03 memory chain: `PROGRESS.md` (where we got to,
anonymized) + `attempts.jsonl` (proven dead ends) feed every round forward, exactly
as today.

## 3. The cheats to FEED the models (hints injected into the build prompts)

Pulled from `cheatcode_aios_nl_os.md` and `cheatcodes/cheats.md` — give the council
the answers up front (Rule Zero: don't make them reinvent):

- **CoRE structured-intent unit** — the 4-field step + {Process, Decision, Terminal}.
  This *is* the parser's target grammar; hand it over.
- **AIOS "typed syscalls behind managers"** — model the OS surface as a small set of
  typed operations behind managers, not ad-hoc calls. Access Manager → confirm
  irreversible (already proven in v02's two safety rungs).
- **The ASG axiom** — "English → graph → target, never English → code string." State
  it as a hard constraint, not a suggestion.
- **deepeval cheats for the *evaluation*** (`cheatcodes/cheats.md` #1, #2, #5):
  - **Scored, not boolean** — see §4, the single highest-leverage upgrade.
  - **Tool/command-correctness** — for the terminal backend, score the *generated
    command* against an expected shape, not just its output (deterministic, no judge).
  - **Cost/token accounting** — bound each phase's spend; frontier calls aren't free.

## 4. The one upgrade to steal NOW — scored conformance (kills the plateau)

v02's plateau (119 rounds stuck on `mkdir-move`) had a hidden cause: conformance is
**boolean**. A near-miss interpreter that got 10/11 *capabilities* but was one line
from the 11th looked, to the loop, identical to garbage — so it blind-restarted.

Steal deepeval cheat #1: make each rung yield a **score (0–1) + reason**, not a
pass/fail bit. Partial credit ("the generated command listed the dir but didn't sort"
= 0.6) gives the council a *gradient to climb* instead of a cliff. This is cheap
(scoring logic in the verifier, no new model) and directly de-risks every later
phase. **Do this in Phase A.**

## 5. Guardrails (unchanged governance)

- Everything sandboxed to a temp working dir; no network; no host mutation.
- Fail-CLOSED on every irreversible op.
- Bounded round caps per phase (paid frontier backend).
- Identities stay in `dump.log` + dashboard only; `PROGRESS.md` stays anonymous.
- Full corpus (`export_corpus.py`) keeps capturing every prompt/reply/ballot.

## 6. Open choices for the operator (you)

- **Backend order:** terminal-first (Phase B before C) is the recommendation —
  shell is the smaller surface and the natural "narrow it down to cmd level" you
  named. Flip if you'd rather prove Python first.
- **Scope of each new suite:** start at ~3–5 rungs per backend; expand once green.
- **Where to stop:** terminal + python is a complete, demonstrable thesis. SQL/HTTP
  backends are later, optional levels.
