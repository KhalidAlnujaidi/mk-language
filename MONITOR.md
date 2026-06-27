# Monitoring charter — NL→OS council experiment

_The standing goals + loop Claude uses to watch this experiment unattended. The
scheduled wake-up reads this file so the goals survive context resets._

## Beacon dashboard (Tailscale)
- http://concomp.tailfe113f.ts.net:8800  (MagicDNS — durable link)
- http://100.64.164.41:8800              (raw tailnet IP)
- LAN fallback: http://192.168.0.19:8800
Reachable from any device on the tailnet; the dashboard binds 0.0.0.0 and only reads
the run's files, so it can never interfere.

## What "good" looks like
The council (5 models, anonymous Borda, governed by axioms) is building, by
execution-gated consensus, a natural-language → OS abstraction layer seeded from the
AIOS/CoRE cheat code. Done = 11/11 conformance rungs execute to their expected OS
outcome under the council's own interpreter (`interpreter.py`), including the two
fail-closed safety rungs.

## Goals (priority order)
1. **Liveness / self-heal.** `run.py` must be alive and `dump.log` growing. If dead:
   read `run.err`, then relaunch detached (resumable — the incumbent source is the
   checkpoint). Record the restart + suspected cause. This is the top guardrail: the
   run has died before from launch mistakes, not the code.
2. **Progress.** Track `capabilities.json` score. Log the FIRST rung that lights up and
   every later gain to `OBSERVATIONS.md` with the anonymized milestone from
   `PROGRESS.md`. The pivotal moment is the first non-zero score (variation→selection
   flips from parallel guessing to iterating one shared interpreter).
3. **Plateau / fresh-start.** Note when the plateau-breaker fires (PROGRESS.md) and
   whether the sideways re-derivation actually escapes the local optimum.
4. **Hygiene.** `run.err` should stay quiet; the experiment dir shouldn't balloon
   (temp sandboxes are wiped per test — watch for leftover `oslang_*` dirs in $TMPDIR).
5. **Completion.** At 11/11: capture `COMPLETE.md` + `interpreter.py`, announce
   proactively, and stop the watch loop.

## Active experiment — failure-memory injection (from round 117)
Each build round now records its strongest FAILED attempts on the active target (code +
exact error) to `attempts.jsonl`, and injects the last 3 distinct failures into the next
prompt ("proven dead ends — take a structurally different path"). Backfilled from dump.log
so round 117 started with memory. Goal: stop the blind-restart loop that re-derived the
same plateau (rounds 108 & 115 were byte-identical).
- **Measure it:** `.venv/bin/python projects/language/impact.py --since 117`
- **Leading indicator (before 11/11):** the recurring `listed-empty` mode (dir made but
  `list files in logs` returns empty — the real wall) should stop recurring, and NEW
  signatures should appear post-117. Watch `signatures only seen AFTER round 117` + `PASS`.
- **If after ~6–8 rounds `listed-empty` still recurs untouched:** memory alone didn't help;
  escalate (partial credit for near-misses, or seed a path-aware FS layer).
- **Model count:** holding at 5 deliberately — changing it now would confound this
  measurement. A/B 3-vs-5 only AFTER the memory impact is read.

## The loop (rough, self-paced)
Every ~30 min, one read-only sweep:
  alive? → score vs last → PROGRESS tail → run.err tail → disk.
Then ACT only when needed (restart if dead; append OBSERVATIONS on a gain; proactive
ping on first-rung / plateau-escape / completion / crash). One-line digest each tick.
Reschedule ~30 min unless: complete, a STOP sentinel exists, or the user says stop.

## Escalation
- Proactive notify on: first rung lit, completion, or a crash that won't restart.
- Otherwise stay quiet (a silent digest in the loop is fine; don't spam).
