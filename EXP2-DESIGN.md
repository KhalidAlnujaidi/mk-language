# Experiment 2 — Governed self-enhancement of Kinox (design only; not yet built)

> Thesis (user): an unharnessed, high-volume, high-temperature LLM is *pure noise* —
> random token generation. But noise + a strong governance harness + axioms + a
> resourceful environment can produce **self-evolution**: a model/agent that scans
> its environment, harvests what raises its capability, compresses reasoning into
> lookup/routing, and gets measurably more capable over time. This experiment runs
> that loop and records everything, to see what emerges from governed noise.

This is the **Darwin-Gödel frontier** version of the skill-evolution loop already in
`products/evolve/`: there the agent only added skills; here it may modify code,
harvest from the machine, and reshape itself — which is far more powerful and far
more dangerous. The whole design is therefore about the **safety boundary**.

## 1. The two roles (both are Kinox)

- **ENFORCER** (high standards, low temperature). Reads the current state, the
  axioms, and the last cycle's result. Its job: *demand* a specific, measurable
  improvement and judge whether the developer delivered. It never writes code — it
  sets the target and grades the outcome. It is the dissatisfied senior who keeps
  raising the bar. ("Your routing still reasons from scratch every call — replace
  it with a lookup table and prove it's faster on the eval, or it doesn't ship.")
- **DEVELOPER** (resourceful, higher temperature). Given the enforcer's target,
  it acts: scans the sandbox + (read-only) the desktop/corpus for something
  reusable, harvests it, writes/edits code in the sandbox, runs the tests, and
  reports. It is the tool-calling agent loop we already built (`products/agent/`),
  pointed at the sandbox with write + bash enabled.

One cycle = enforcer sets target → developer attempts → enforcer + the **immutable
verifier** judge → keep iff better. Loop forever (until STOP / budget / no-improve).

## 2. The safety boundary (the entire point)

| Concern | Control |
|---|---|
| Don't wreck real Kinox | Operates ONLY on a **throwaway clone** (`/tmp/kinox-evolve-<ts>/`), made from the pushed git HEAD. The real repo is never in its write set. Disposable — it's on GitHub. |
| "Copies whatever is on the device" | Desktop + corpus are mounted **read-only**. The developer may *read* anywhere it's allowed and *copy into the sandbox only*. Never writes outside the sandbox. |
| Reward-hacking | The verifier (the test suite + a held-out eval set) lives **outside the sandbox** and is **immutable** to the developer (protected-paths guard, fail-CLOSED). A cycle is kept only if the verifier score goes up and the suite stays green. It cannot weaken its own judge. |
| Runaway resources | Per-cycle caps: wall-clock, max bash time, max files copied, max sandbox size on disk; one model resident at a time; no network egress for the developer except Ollama. A daemon watchdog kills a cycle that exceeds caps (fail-CLOSED). |
| Don't break what works | Git inside the sandbox: each kept cycle is a commit; a rejected cycle is `git reset --hard`. Full reversibility. |
| Secrets / junk harvest | Copy filter: skip dotfiles, keys, `.env`, binaries, anything > N MB; log every harvested path to the dump for audit. |

## 3. Mechanics (reuse, don't reinvent — Rule Zero)

- **Developer** = `products/agent/run_agent` with a sandbox-rooted `ToolRegistry`
  (`read_file`, `list_dir`, **write_file**, **run_bash** all sandbox-scoped) + the
  `find_skill`/`load_skill` bridge + a new read-only `scan(path, query)` tool over
  the desktop/corpus.
- **Enforcer** = a single low-temp completion that emits a target spec + a grade.
- **Verifier** = `pytest` in the sandbox + a held-out eval set (the
  `products/evolve` challenge style, immutable).
- **Selection** = keep the cycle's commit iff `tests green AND eval_score_delta > 0`;
  else hard-reset. Same governed-evolution rule as exp-1, one level up.
- **Recording** = the same append-only fsync'd `dump.log`: enforcer target,
  developer reasoning + every tool call, harvested paths, test output, verdict.
- **Stop/resume** = STOP sentinel + signal handler + per-cycle git commit as the
  checkpoint. Resumes from the last kept commit. Nothing lost on stop.

## 4. What we're watching for (the emergence question)

- Does it actually find reusable parts on the machine and assimilate them?
- Does it ever do what the thesis predicts — **replace reasoning with lookup/routing**
  (caching, dispatch tables, precomputed indexes) to get faster without a bigger
  model? That specific move is the headline result if it happens.
- Or does it stall / churn / reward-hack-attempt (and get caught)? Every outcome
  is a logged data point about governed-noise → capability.

## 5. Open decisions to settle before building
- The held-out eval set that defines "more capable" (without it, there's no fitness
  — the loop degenerates to noise). Likely: agent task-completion rate + latency.
- Cap values (wall-clock/cycle, disk, files).
- Which model(s) drive enforcer vs developer (GPU-shared with exp-1, so small/resident
  if run concurrently, or full models if run after exp-1).

**Status: design only. No code, no clone, nothing running. Build on your go.**
