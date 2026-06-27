# Beacon monitoring goals — the contract the loop enforces

The cluster runs the governed self-development loop 24/7. These are the goals I
(the monitoring agent) hold it to. Each is a **deterministic check** in
`products/beacon/monitor.py` (ground truth → plain code), run on a rough timer.
The loop reads the verdict and acts; it escalates to the human only on a real
decision.

| Goal | Healthy means | If breached, the loop… |
|------|---------------|------------------------|
| **G1 Liveness** | harness + dashboard processes up; dashboard answers; tailnet URL serves | restart via `beacon-run.sh restart`; if it won't stay up, escalate with the log tail |
| **G2 Cluster** | inference Service up with the model; DaemonSet 3/3 ready | `kubectl rollout restart ds/kinox-ollama -n kinox`; if pods OOM/CrashLoop, escalate |
| **G3 Progress** | cycle count advancing, or honestly idling (nothing failing) | inspect `harness.log`; restart harness if wedged |
| **G4 Benefit** | kept evolutions appear over time, OR the loop is idling (not thrashing) | if ≥12 cycles with 0 findings and not idling → propose tuning (more challenges / stronger model) and escalate |
| **G5 No-runaway** | recent pitfalls are normal rejections (not all errors); vast.ai has **no** running instance | on a vast.ai instance → destroy it; on all-error pitfalls → treat as cluster outage (G2) |

## Loop cadence & escalation
- **Cadence:** rough, self-paced — ~30 min between checks (the loop is slow; cycles take ~2 min and idle 5 min). Tighten only when actively chasing a fault.
- **Act silently** for: restarting a dead process, re-rolling a stuck DaemonSet, destroying a stray vast.ai instance, recording a verdict.
- **Escalate to the human** for: anything that won't self-heal after one restart, a benefit stall needing a tuning decision (G4), or unexpected spend.
- **Stop condition:** the human says stop, or the project is intentionally torn down.

## Verdict trail
Every check appends a `monitor` event (overall OK/WARN/FAIL + per-goal detail)
to `var/beacon/ledger.jsonl`, so the history of "was it healthy?" is auditable
alongside the findings and pitfalls — honest observability for the watchdog too.
