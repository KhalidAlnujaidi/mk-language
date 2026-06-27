"""Measure the impact of failure-memory injection. Reads dump.log and reports, per
build round: best score, and the DISTINCT `mkdir-move` failure signatures seen that
round. Splits at the resume boundary (--since) into BEFORE (blind restart) vs AFTER
(memory-injected) so you can see whether the council stops repeating dead ends and
starts producing genuinely new approaches — the leading indicator of escape, visible
well before 11/11.

Usage:  .venv/bin/python projects/language/impact.py [--since ROUND]
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
DUMP = HERE / "dump.log"
TARGET = "mkdir-move"

HEADER = re.compile(r"^===== \[.*?\] (.*?) =====$")
EVAL = re.compile(r"^BUILD eval model=(\S+) round=(\d+) mode=")
SCORE = re.compile(r"score=(\d+)/(\d+)")
MKDIR = re.compile(r"^mkdir-move: (.*)$", re.M)


def signature(detail: str) -> str:
    """Collapse a raw mkdir-move result to a failure CLASS, so repeats are obvious."""
    detail = detail.strip()
    if detail == "PASS":
        return "PASS"
    if detail == "timeout":
        return "timeout"
    if "NO_RUN_FUNCTION" in detail:
        return "no-run-function"
    if "missing 1 required positional" in detail:
        return "run-signature-mismatch"
    if "FileNotFoundError" in detail and "create file" in detail:
        return "program-treated-as-path"
    m = re.search(r"got=('(?:[^']*)'|\"[^\"]*\")", detail)
    if m:
        got = m.group(1)
        if got in ("''", '""'):
            return "empty-output"
        if "empty" in got:
            return "listed-empty (dir made, move/list-in-subdir failed)"
        return f"wrong-output:{got[:40]}"
    em = re.search(r"err=(\w+(?:Error)?)", detail)
    return f"error:{em.group(1)}" if em else "other"


def sections(text: str):
    head, body = None, []
    for line in text.splitlines():
        m = HEADER.match(line)
        if m:
            if head is not None:
                yield head, "\n".join(body)
            head, body = m.group(1), []
        else:
            body.append(line)
    if head is not None:
        yield head, "\n".join(body)


def main() -> None:
    since = None
    if "--since" in sys.argv:
        since = int(sys.argv[sys.argv.index("--since") + 1])
    rounds: dict[int, dict] = {}
    for head, body in sections(DUMP.read_text(encoding="utf-8", errors="replace")):
        m = EVAL.match(head)
        if not m:
            continue
        rnd = int(m.group(2))
        sm = SCORE.search(body)
        n = int(sm.group(1)) if sm else 0
        dm = MKDIR.search(body)
        sig = signature(dm.group(1)) if dm else "n/a"
        r = rounds.setdefault(rnd, {"best": 0, "sigs": set()})
        r["best"] = max(r["best"], n)
        r["sigs"].add(sig)

    if not rounds:
        print("no build rounds in dump.log yet.")
        return

    seen_all: set[str] = set()
    print(f"{'round':>6} {'best':>5}  new?  mkdir-move failure signatures")
    print("-" * 78)
    for rnd in sorted(rounds):
        r = rounds[rnd]
        fresh = r["sigs"] - seen_all
        seen_all |= r["sigs"]
        mark = "NEW " if fresh else "    "
        tag = ""
        if since is not None and rnd >= since:
            tag = " <-- AFTER (memory)" if rnd == since else ""
        if "PASS" in r["sigs"]:
            mark = "PASS"
        print(f"{rnd:>6} {r['best']:>4}/11  {mark}  {', '.join(sorted(r['sigs']))}{tag}")

    print("-" * 78)
    print(f"distinct failure signatures ever seen: {len(seen_all)}")
    if since is not None:
        pre = {s for rnd, r in rounds.items() if rnd < since for s in r["sigs"]}
        post = {s for rnd, r in rounds.items() if rnd >= since for s in r["sigs"]}
        print(f"signatures only seen AFTER round {since} (new exploration): "
              f"{sorted(post - pre) or '— none yet —'}")
        print(f"PASS reached: {'YES' if 'PASS' in post else 'not yet'}")


if __name__ == "__main__":
    main()
