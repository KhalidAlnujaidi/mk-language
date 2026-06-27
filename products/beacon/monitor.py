"""Watchdog — the deterministic health check behind the monitoring loop.

Monitoring "is the project healthy?" has ground truth (a process is up or it is
not; the cycle count advanced or it did not), so it is plain code, not a model
judging vibes (thesis #1). This module checks each goal, appends a ``monitor``
verdict to the ledger, prints JSON, and exits 0/1/2 for OK/WARN/FAIL. The loop
(a human-or-agent on a timer) reads the verdict and *acts* — restart a dead
process, escalate a decision. Checking and acting are kept separate on purpose.

Goals (see products/beacon/GOALS.md):
  G1 Liveness  — harness + dashboard up, dashboard answers, tailnet URL serves.
  G2 Cluster   — inference Service up with the model; DaemonSet 3/3 ready.
  G3 Progress  — cycles advancing; ledger still growing.
  G4 Benefit   — findings appear over time, or the loop is honestly idling
                 (not thrashing 0-benefit cycles forever).
  G5 No-runaway— pitfalls aren't all errors (a silent cluster outage), and
                 vast.ai stays empty (no surprise cloud spend).
"""

from __future__ import annotations

import json
import subprocess
import time
import urllib.request
from pathlib import Path

from products.beacon.harness import LEDGER_PATH, VAR
from products.beacon.ledger import Ledger

OK, WARN, FAIL = "OK", "WARN", "FAIL"
_RANK = {OK: 0, WARN: 1, FAIL: 2}
LOCAL = "http://127.0.0.1:8808"
TAILNET_IP = "100.64.164.41"


def _http_json(url: str, timeout: float = 5.0) -> dict | None:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:
            return json.loads(r.read().decode())
    except Exception:
        return None


def _pid_alive(name: str) -> bool:
    pid_file = VAR / f"{name}.pid"
    try:
        pid = int(pid_file.read_text().strip())
        (Path("/proc") / str(pid)).stat()
        return True
    except Exception:
        return False


def _kubectl_ready() -> tuple[int, int]:
    try:
        out = subprocess.run(
            ["kubectl", "get", "ds", "kinox-ollama", "-n", "kinox",
             "-o", "jsonpath={.status.numberReady}/{.status.desiredNumberScheduled}"],
            capture_output=True, text=True, timeout=10,
        ).stdout.strip()
        ready, desired = out.split("/")
        return int(ready or 0), int(desired or 0)
    except Exception:
        return -1, -1


def _vast_clean() -> bool | None:
    """True iff vast.ai has no running instances (no spend). None if unknown."""
    key_file = Path.home() / ".config" / "vastai" / "vast_api_key"
    try:
        key = key_file.read_text().strip()
        req = urllib.request.Request(
            "https://console.vast.ai/api/v0/instances/",
            headers={"Authorization": f"Bearer {key}"},
        )
        with urllib.request.urlopen(req, timeout=8) as r:
            data = json.loads(r.read().decode())
        ins = data.get("instances", data if isinstance(data, list) else [])
        return all(o.get("actual_status") != "running" for o in ins)
    except Exception:
        return None


def check() -> dict:
    led = Ledger(LEDGER_PATH)
    rows = led.read()
    prev = [r for r in rows if r.get("kind") == "monitor"]
    goals: list[dict] = []

    def g(gid: str, name: str, status: str, detail: str) -> None:
        goals.append({"id": gid, "name": name, "status": status, "detail": detail})

    # G1 — liveness
    state = _http_json(f"{LOCAL}/api/state")
    tail_ok = _http_json(f"http://{TAILNET_IP}:8808/api/state") is not None
    h_up, s_up = _pid_alive("harness"), _pid_alive("server")
    if h_up and s_up and state is not None:
        g("G1", "liveness", OK if tail_ok else WARN,
          f"harness={h_up} server={s_up} dashboard=up "
          f"tailnet={'up' if tail_ok else 'DOWN'}")
    else:
        g("G1", "liveness", FAIL,
          f"harness={h_up} server={s_up} dashboard={'up' if state else 'DOWN'}")

    # G2 — cluster
    cl = (state or {}).get("cluster", {})
    ready, desired = _kubectl_ready()
    if cl.get("up") and cl.get("models"):
        g("G2", "cluster", OK if ready == desired and desired > 0 else WARN,
          f"service=up models={cl.get('models')} daemonset={ready}/{desired}")
    else:
        g("G2", "cluster", FAIL,
          f"service down or no model; daemonset={ready}/{desired}")

    # G3 — progress
    counts = (state or {}).get("counts", {})
    cycles = counts.get("cycles", 0)
    last_cycles = prev[-1].get("cycles", 0) if prev else 0
    health = (state or {}).get("health", {})
    idle = (health.get("decision") == "all-pass")
    if cycles > last_cycles or idle:
        g("G3", "progress", OK, f"cycles {last_cycles}→{cycles} (idle={idle})")
    elif not prev:
        g("G3", "progress", OK, f"first check, cycles={cycles}")
    else:
        g("G3", "progress", WARN, f"cycles stuck at {cycles} since last check")

    # G4 — benefit
    findings, pitfalls = counts.get("findings", 0), counts.get("pitfalls", 0)
    if findings > 0:
        g("G4", "benefit", OK, f"{findings} kept evolution(s)")
    elif idle:
        g("G4", "benefit", OK, "no findings yet but honestly idling (nothing failing)")
    elif cycles >= 12:
        g("G4", "benefit", WARN,
          f"{cycles} cycles, 0 findings, {pitfalls} pitfalls — tune challenges/model")
    else:
        g("G4", "benefit", OK, f"warming up ({cycles} cycles, {findings} findings)")

    # G5 — no runaway
    vast = _vast_clean()
    recent_pitfalls = [r for r in rows if r.get("kind") == "pitfall"][-5:]
    all_errors = bool(recent_pitfalls) and all(
        r.get("kind_of") == "exception" for r in recent_pitfalls)
    if all_errors:
        g("G5", "no-runaway", FAIL,
          "last 5 pitfalls are all exceptions — likely cluster outage")
    elif vast is False:
        g("G5", "no-runaway", FAIL, "vast.ai has a RUNNING instance — unexpected spend")
    else:
        g("G5", "no-runaway", OK,
          f"vast={'clean' if vast else 'unknown'}; "
          "pitfalls look like normal rejections")

    overall = max((x["status"] for x in goals), key=lambda s: _RANK[s])
    verdict = {
        "ts": time.time(), "overall": overall, "cycles": cycles,
        "findings": findings, "pitfalls": pitfalls, "goals": goals,
    }
    led.record("monitor", **{k: v for k, v in verdict.items() if k != "ts"})
    return verdict


def main() -> int:
    v = check()
    print(json.dumps(v, indent=2))
    return _RANK[v["overall"]]


if __name__ == "__main__":
    raise SystemExit(main())
