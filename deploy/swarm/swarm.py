#!/usr/bin/env python3
"""kinox swarm orchestrator (stdlib-only).

Drives the live vast.ai rented-GPU fleet as a map-reduce codegen pool. The nodes
serve Ollama (OpenAI-compatible) on :11434; we reach them over SSH and curl the
on-box endpoint (no port mapping needed). This is the proven 2026-06-22 method
from the `vast-swarm` skill, made repeatable.

    swarm.py status                 # probe every running node, print ready pool
    swarm.py pull [model]           # pull the fleet-standard model onto all nodes
    swarm.py dispatch <jobs.json>   # fan {id,model?,prompt} jobs across the pool

`dispatch` writes one <out_dir>/<job_id>.json per result (raw completion text +
which node/model served it). Integration/verification stays LOCAL — the swarm
only drafts; the home box reviews with TDD before anything is committed.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed

# Fleet-standard model: the single specialist every node serves for codegen.
# Switched 2026-06-23 to OpenCodeReasoning-Nemotron-14B (highest-performing coder
# in the cocktail). dispatch() targets this unless a job overrides `model`.
STD_MODEL = "hf.co/bartowski/nvidia_OpenCodeReasoning-Nemotron-14B-GGUF:Q4_K_M"

VASTAI = os.path.expanduser("~/.local/bin/vastai")
KEY = os.path.expanduser("~/.ssh/id_ed25519")
SSHOPTS = [
    "-o",
    "StrictHostKeyChecking=no",
    "-o",
    "UserKnownHostsFile=/dev/null",
    "-o",
    "ConnectTimeout=15",
    "-i",
    KEY,
]


def list_running() -> list[dict]:
    """Every running instance with an ssh endpoint, as {id,label,host,port}."""
    out = subprocess.run(
        [VASTAI, "show", "instances", "--raw"],
        capture_output=True,
        text=True,
    ).stdout
    nodes = []
    for o in json.loads(out):
        if o.get("actual_status") == "running" and o.get("ssh_host"):
            nodes.append(
                {
                    "id": o["id"],
                    "label": o.get("label", str(o["id"])),
                    "host": o["ssh_host"],
                    "port": o["ssh_port"],
                    "gpu": o.get("gpu_name", "?"),
                }
            )
    return nodes


def _ssh(node: dict, remote_cmd: str, timeout: int) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["ssh", *SSHOPTS, "-p", str(node["port"]), f"root@{node['host']}", remote_cmd],
        capture_output=True,
        text=True,
        timeout=timeout,
    )


def probe(node: dict) -> dict:
    """Return node with its served models (empty list = not ready yet)."""
    try:
        r = _ssh(node, "curl -s http://localhost:11434/v1/models", timeout=25)
        data = json.loads(r.stdout)
        node["models"] = [m["id"] for m in data.get("data", [])]
    except Exception as e:  # noqa: BLE001 - report, don't crash the sweep
        node["models"] = []
        node["error"] = str(e)[:80]
    return node


def status() -> list[dict]:
    nodes = list_running()
    ready = []
    with ThreadPoolExecutor(max_workers=16) as ex:
        for n in ex.map(probe, nodes):
            tag = ",".join(m.split("/")[-1] for m in n["models"]) or "(loading/none)"
            print(f"{n['label']:16} {n['host']}:{n['port']:<6} {n['gpu']:10} -> {tag}")
            if n["models"]:
                ready.append(n)
    print(f"\n{len(ready)}/{len(nodes)} nodes serving a model.")
    return ready


def pull(model: str = STD_MODEL, timeout: int = 1800) -> None:
    """Pull *model* onto every running node in parallel (idempotent in Ollama).

    Standardizes the fleet on one specialist. Nodes that already have it return
    immediately. ~9GB for the Nemotron-14B Q4, so allow a long timeout.
    """
    nodes = list_running()
    print(f"pulling {model.split('/')[-1]} onto {len(nodes)} nodes...\n")

    def do(node: dict) -> tuple[str, bool, str]:
        try:
            r = _ssh(node, f"ollama pull {model} 2>&1 | tail -1", timeout=timeout)
            line = (
                (r.stdout or r.stderr).strip().splitlines()[-1]
                if (r.stdout or r.stderr).strip()
                else ""
            )
            ok = "success" in line.lower() or r.returncode == 0
            return node["label"], ok, line[:80]
        except Exception as e:  # noqa: BLE001
            return node["label"], False, str(e)[:80]

    with ThreadPoolExecutor(max_workers=16) as ex:
        for label, ok, msg in ex.map(do, nodes):
            print(f"[{'OK ' if ok else 'ERR'}] {label:16} {msg}")


def _run_job(node: dict, model: str, prompt: str, timeout: int) -> str:
    """curl the on-box OpenAI endpoint; return the assistant text."""
    payload = json.dumps(
        {"model": model, "messages": [{"role": "user", "content": prompt}]}
    )
    # single-quote the JSON for the remote shell; escape embedded single quotes
    safe = payload.replace("'", "'\\''")
    cmd = (
        "curl -s http://localhost:11434/v1/chat/completions "
        "-H 'Content-Type: application/json' "
        f"-d '{safe}'"
    )
    r = _ssh(node, cmd, timeout=timeout)
    resp = json.loads(r.stdout)
    return resp["choices"][0]["message"]["content"]


def dispatch(jobs_path: str, out_dir: str = "swarm_out", timeout: int = 600) -> None:
    with open(jobs_path) as fh:
        jobs = json.load(fh)
    os.makedirs(out_dir, exist_ok=True)
    pool = status()
    if not pool:
        print("no ready nodes; aborting", file=sys.stderr)
        sys.exit(1)

    def work(i_job):
        i, job = i_job
        node = pool[i % len(pool)]
        model = job.get("model") or STD_MODEL
        try:
            text = _run_job(node, model, job["prompt"], timeout)
            result = {
                "job": job["id"],
                "node": node["label"],
                "model": model,
                "ok": True,
                "output": text,
            }
        except Exception as e:  # noqa: BLE001
            result = {
                "job": job["id"],
                "node": node["label"],
                "model": model,
                "ok": False,
                "error": str(e)[:200],
            }
        with open(os.path.join(out_dir, f"{job['id']}.json"), "w") as fh:
            json.dump(result, fh, indent=2)
        flag = "OK" if result["ok"] else "ERR"
        print(f"[{flag}] {job['id']:24} <- {node['label']} ({model.split('/')[-1]})")
        return result

    print(f"\ndispatching {len(jobs)} jobs across {len(pool)} nodes...\n")
    with ThreadPoolExecutor(max_workers=min(len(pool), 16)) as ex:
        futs = [ex.submit(work, ij) for ij in enumerate(jobs)]
        results = [f.result() for f in as_completed(futs)]
    ok = sum(1 for r in results if r["ok"])
    print(f"\n{ok}/{len(results)} jobs returned. results in {out_dir}/")


if __name__ == "__main__":
    if len(sys.argv) < 2 or sys.argv[1] not in ("status", "dispatch", "pull"):
        print(__doc__)
        sys.exit(2)
    if sys.argv[1] == "status":
        status()
    elif sys.argv[1] == "pull":
        pull(*(sys.argv[2:3] or []))
    else:
        dispatch(sys.argv[2], *(sys.argv[3:4] or []))
