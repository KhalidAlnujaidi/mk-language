#!/usr/bin/env python3
"""Extract the pytest code block from each swarm draft into tests/eval/.

Swarm nodes return reasoning + a ```python fenced block. We take the LARGEST
fenced python block (the actual test, not a snippet quoted mid-reasoning),
strip it, and write tests/eval/test_<key>.py. Curation/verification is the
caller's job (run pytest, keep green, fix/discard red).
"""

import json
import os
import re
import sys

SRC = "deploy/swarm/swarm_out"
DST = "tests/eval"

FENCE = re.compile(r"```(?:python)?\s*\n(.*?)```", re.DOTALL)


def extract(text: str) -> str | None:
    blocks = FENCE.findall(text)
    if not blocks:
        return None
    # largest block = the real test, not an inline snippet
    return max(blocks, key=len).strip()


def main() -> None:
    os.makedirs(DST, exist_ok=True)
    open(os.path.join(DST, "__init__.py"), "w").close()
    n_ok = 0
    for fn in sorted(os.listdir(SRC)):
        if not fn.endswith(".json"):
            continue
        with open(os.path.join(SRC, fn)) as fh:
            rec = json.load(fh)
        key = rec["job"].replace("eval-", "")
        if not rec.get("ok"):
            print(f"[skip] {key}: job errored ({rec.get('error', '?')[:60]})")
            continue
        code = extract(rec["output"])
        if not code:
            print(f"[skip] {key}: no python block found")
            continue
        path = os.path.join(DST, f"test_{key}.py")
        header = f"# swarm-drafted ({rec['node']}, Nemotron-14B); curated locally\n"
        with open(path, "w") as f:
            f.write(header)
            f.write(code + "\n")
        print(f"[ok]   {key}: {len(code)} chars -> {path}")
        n_ok += 1
    print(f"\nextracted {n_ok} test files into {DST}/")


if __name__ == "__main__":
    sys.exit(main())
