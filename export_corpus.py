"""Build a tagged, structured corpus from the council's raw audit log.

Nothing is invented or summarized here — this is a *faithful* re-tagging of the
append-only `dump.log` (which already captures EVERY prompt, raw reply, ballot,
build-eval and error, fsync'd per call) into machine-queryable records, so the
whole evolution is reusable for future reference / training / analysis.

Outputs (under ``corpus/``):
  - ``council_corpus.jsonl``  — one JSON record per logged section (full bodies)
  - ``INDEX.md``              — human-readable summary: counts by kind/model/round
  - ``rounds/``               — (optional) the per-round machine logs are already
                                in ``rounds/`` ; this just cross-references them.

Run:  .venv/bin/python projects/language/export_corpus.py
It is incremental-safe: it always rewrites from the full dump (cheap, deterministic).
"""

from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
DUMP = HERE / "dump.log"
OUT = HERE / "corpus"
SECTION = re.compile(r"^===== \[(?P<ts>[^\]]+)\] (?P<head>.*?) =====$")


def _attrs(head: str) -> tuple[str, dict[str, str]]:
    """Split a section header into (kind, key=value attrs).

    e.g. ``PROMPT model=openai/gpt-4o tag=interp temp=0.9`` ->
         ("PROMPT", {model:..., tag:interp, temp:0.9})."""
    toks = head.split()
    attrs: dict[str, str] = {}
    kind_parts: list[str] = []
    for t in toks:
        if "=" in t and not t.startswith("="):
            k, v = t.split("=", 1)
            attrs[k] = v
        else:
            kind_parts.append(t)
    return " ".join(kind_parts) or "?", attrs


def _split_prompt(body: str) -> dict[str, str]:
    """A PROMPT body is ``--- system ---\\n…\\n--- user ---\\n…`` — split it so the
    system axioms and the per-round user payload are separately queryable."""
    m = re.search(r"--- system ---\n(.*?)\n--- user ---\n(.*)", body, re.DOTALL)
    if m:
        return {"system": m.group(1).strip(), "user": m.group(2).strip()}
    return {}


def export() -> dict[str, object]:
    OUT.mkdir(exist_ok=True)
    text = DUMP.read_text(encoding="utf-8", errors="replace")
    lines = text.splitlines()

    records: list[dict[str, object]] = []
    cur: dict[str, object] | None = None
    body: list[str] = []
    cur_round: int | None = None
    cur_phase: str | None = None

    def flush() -> None:
        nonlocal cur, body
        if cur is None:
            return
        cur["body"] = "\n".join(body).strip()
        cur["chars"] = len(cur["body"])
        if cur["kind"] == "PROMPT":
            cur.update(_split_prompt(cur["body"]))
        records.append(cur)
        cur, body = None, []

    for ln in lines:
        m = SECTION.match(ln)
        if not m:
            if cur is not None:
                body.append(ln)
            continue
        flush()
        kind, attrs = _attrs(m.group("head"))
        # Track the round/phase context so every record carries it, even prompts
        # that don't name a round in their own header.
        if "round" in attrs:
            try:
                cur_round = int(attrs["round"])
            except ValueError:
                pass
        if kind == "RUN START":
            # round/phase land in the body line: "round=N phase=P roster=(...)"
            pass
        if "phase" in attrs:
            cur_phase = attrs["phase"]
        cur = {
            "seq": len(records),
            "ts": m.group("ts"),
            "kind": kind,
            "model": attrs.get("model", ""),
            "tag": attrs.get("tag", ""),
            "attempt": attrs.get("attempt", ""),
            "mode": attrs.get("mode", ""),
            "round": attrs.get("round", cur_round if cur_round is not None else ""),
            "phase": cur_phase or "",
        }

    flush()

    # Second pass: RUN START bodies carry round=/phase= — backfill the round context
    # forward so nearby prompts inherit it.
    last_round = ""
    for r in records:
        if r["kind"] == "RUN START":
            mr = re.search(r"round=(\d+)\s+phase=(\S+)", str(r["body"]))
            if mr:
                last_round, r["round"], r["phase"] = mr.group(1), mr.group(1), mr.group(2)
        elif not r["round"] and last_round:
            r["round"] = last_round

    # Write the JSONL corpus (full bodies — maximum detail, nothing dropped).
    jsonl = OUT / "council_corpus.jsonl"
    with jsonl.open("w", encoding="utf-8") as fh:
        for r in records:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")

    # Summary index.
    by_kind = Counter(str(r["kind"]) for r in records)
    by_model = Counter(str(r["model"]) for r in records if r["model"])
    by_tag = Counter(str(r["tag"]) for r in records if r["tag"])
    total_chars = sum(int(r["chars"]) for r in records)
    rounds_seen = sorted({int(r["round"]) for r in records if str(r["round"]).isdigit()})

    idx = [
        "# Council corpus — index",
        "",
        f"Faithful re-tagging of `dump.log` → `council_corpus.jsonl`.",
        f"Every prompt, raw reply, ballot, build-eval and error, tagged and queryable.",
        "",
        f"- **records:** {len(records)}",
        f"- **total text:** {total_chars:,} chars (~{total_chars // 4:,} tokens)",
        f"- **rounds covered:** {rounds_seen[0] if rounds_seen else '—'}"
        f"–{rounds_seen[-1] if rounds_seen else '—'} ({len(rounds_seen)} rounds)",
        "",
        "## by kind",
        *[f"- `{k}` — {v}" for k, v in by_kind.most_common()],
        "",
        "## by model (calls logged)",
        *[f"- `{k}` — {v}" for k, v in by_model.most_common()],
        "",
        "## by tag (phase of deliberation)",
        *[f"- `{k}` — {v}" for k, v in by_tag.most_common()],
        "",
        "## query examples",
        "```bash",
        "# every interpreter proposal from the cloud council, round 220:",
        "jq 'select(.kind==\"RAW REPLY\" and .round==\"220\" and (.model|test(\"/\")))' \\",
        "   corpus/council_corpus.jsonl",
        "# every blind ballot:",
        "jq 'select(.tag|test(\"vote\"))' corpus/council_corpus.jsonl",
        "```",
        "",
    ]
    (OUT / "INDEX.md").write_text("\n".join(idx), encoding="utf-8")

    summary = {
        "records": len(records),
        "total_chars": total_chars,
        "rounds": [rounds_seen[0], rounds_seen[-1]] if rounds_seen else [],
        "by_kind": dict(by_kind),
        "by_model": dict(by_model),
    }
    (OUT / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    return summary


if __name__ == "__main__":
    s = export()
    print(f"corpus written: {s['records']} records, "
          f"{s['total_chars']:,} chars -> projects/language/corpus/")
