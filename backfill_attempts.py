"""One-shot: seed attempts.jsonl from the existing dump.log so the council's very
first resumed build round already carries failure memory. Pairs each model's most
recent interpreter RAW REPLY (the code) with its BUILD eval result for `mkdir-move`
(the error), within the rounds where 10/11 was the incumbent and mkdir-move the target."""
from __future__ import annotations

import json
import re
from pathlib import Path

from council import extract_code

HERE = Path(__file__).resolve().parent
DUMP = HERE / "dump.log"
ATTEMPTS = HERE / "attempts.jsonl"
TARGET = "mkdir-move"
MIN_ROUND = 102  # 10/11 first reached at round 101 → from here the target is mkdir-move

HEADER = re.compile(r"^===== \[.*?\] (.*?) =====$")
RAW = re.compile(r"^RAW REPLY model=(\S+) tag=interp")
EVAL = re.compile(r"^BUILD eval model=(\S+) round=(\d+) mode=")
SCORE = re.compile(r"score=(\d+)/(\d+)")
MKDIR = re.compile(r"^mkdir-move: (.*)$", re.M)


def sections(text: str):
    cur_head, cur_body = None, []
    for line in text.splitlines():
        m = HEADER.match(line)
        if m:
            if cur_head is not None:
                yield cur_head, "\n".join(cur_body)
            cur_head, cur_body = m.group(1), []
        else:
            cur_body.append(line)
    if cur_head is not None:
        yield cur_head, "\n".join(cur_body)


def main() -> None:
    last_code: dict[str, str] = {}
    rows: list[dict] = []
    for head, body in sections(DUMP.read_text(encoding="utf-8", errors="replace")):
        m = RAW.match(head)
        if m:
            code = extract_code(body)
            if code:
                last_code[m.group(1)] = code
            continue
        m = EVAL.match(head)
        if not m:
            continue
        model, rnd = m.group(1), int(m.group(2))
        if rnd < MIN_ROUND:
            continue
        sm = SCORE.search(body)
        n = int(sm.group(1)) if sm else 0
        dm = MKDIR.search(body)
        if not dm:
            continue
        detail = dm.group(1).strip()
        if detail == "PASS":
            continue  # only failures are instructive here
        code = last_code.get(model, "")
        if not code:
            continue
        rows.append({"round": rnd, "target": TARGET, "n": n,
                     "error": detail[:200], "code": code})

    # Dedup by code, keep newest, cap to a useful tail.
    seen: set[str] = set()
    kept: list[dict] = []
    for row in reversed(rows):
        key = row["code"][:400]
        if key in seen:
            continue
        seen.add(key)
        kept.append(row)
        if len(kept) >= 10:
            break
    kept.reverse()  # oldest-first in the ledger (recent_failures reads the tail)

    with ATTEMPTS.open("a", encoding="utf-8") as fh:
        for row in kept:
            fh.write(json.dumps(row) + "\n")
    print(f"backfilled {len(kept)} distinct failed mkdir-move attempts "
          f"(from {len(rows)} eval records) -> {ATTEMPTS.name}")


if __name__ == "__main__":
    main()
