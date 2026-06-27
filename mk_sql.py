"""MK · SQL cell — the Principle of Least Generation on WikiSQL.

Reuses the structure of concomp/cbyte/wikisql_core.py (Rule Zero) adapted to the raw
WikiSQL jsonl format (conds as [col, op, val] triples). WikiSQL's grammar is FINITE:

    SELECT [agg] <col> FROM table [WHERE <col> <op> <val> {AND ...}]
    agg ∈ {∅, MAX, MIN, COUNT, SUM, AVG}      op ∈ {=, >, <}

So every query is a slot-fill of a tiny TEMPLATE family. This module measures how few
templates the corpus actually uses (Stage 1 = template mining), then builds a
zero-generation slot-filler + a gate (later stages). `assemble()` is pure string
assembly — 0 LLM tokens — exactly PLG's retrieval tier.
"""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

DATA = Path("/home/enigma/.cache/huggingface/datasets/downloads/extracted/"
            "efc94c46c05d9193bb80eec5a30846ee71a190365c5b3226e90d324b70b5bb01/data")
AGG_OPS = ["", "MAX", "MIN", "COUNT", "SUM", "AVG"]
COND_OPS = ["=", ">", "<", "OP"]


def load(split: str) -> tuple[list[dict], dict[str, dict]]:
    qs = [json.loads(l) for l in (DATA / f"{split}.jsonl").read_text().splitlines() if l]
    tables = {}
    for l in (DATA / f"{split}.tables.jsonl").read_text().splitlines():
        if l:
            t = json.loads(l)
            tables[t["id"]] = t
    return qs, tables


def signature(sql: dict) -> tuple:
    """The template identity (the 'C-Byte shape'): (agg, tuple-of-condition-ops).
    Columns and values are abstracted to slots — this collapses surface queries to
    their structural template, so we can count how few templates the corpus uses."""
    return (AGG_OPS[sql["agg"]], tuple(COND_OPS[c[1]] for c in sql["conds"]))


def assemble(sql: dict, header: list[str]) -> str:
    """Structured intent -> SQL string (WikiSQL human_readable format). Zero tokens."""
    agg = AGG_OPS[sql["agg"]]
    sel = f"{agg} {header[sql['sel']]}" if agg else header[sql["sel"]]
    out = f"SELECT {sel} FROM table"
    parts = [f"{header[c[0]]} {COND_OPS[c[1]]} {c[2]}" for c in sql["conds"]]
    if parts:
        out += " WHERE " + " AND ".join(parts)
    return out


def stage1_template_mining(splits=("train", "dev", "test")) -> None:
    """PLG's central claim, measured: how few templates cover the corpus?"""
    sigs: Counter = Counter()
    ncond: Counter = Counter()
    total = 0
    for sp in splits:
        qs, _ = load(sp)
        for q in qs:
            sigs[signature(q["sql"])] += 1
            ncond[len(q["sql"]["conds"])] += 1
            total += 1

    print(f"=== Stage 1 · template mining  (splits={'+'.join(splits)}, N={total:,}) ===")
    print(f"distinct structural templates (agg, cond-ops): {len(sigs):,}")
    print(f"  -> template SPACE is {len(sigs)} shapes for {total:,} queries "
          f"= {total / len(sigs):,.0f} queries/template\n")

    # coverage curve: how many templates to cover X% of queries
    cum, k = 0, 0
    marks = {50: None, 80: None, 90: None, 95: None, 99: None, 99.9: None}
    for _sig, c in sigs.most_common():
        cum += c
        k += 1
        pct = 100 * cum / total
        for m in marks:
            if marks[m] is None and pct >= m:
                marks[m] = k
    print("coverage curve (templates needed to cover X% of all queries):")
    for m in (50, 80, 90, 95, 99, 99.9):
        print(f"   {m:>5}%  ->  {marks[m]:>4} templates")
    print("\ntop 8 templates by frequency:")
    for sig, c in sigs.most_common(8):
        agg, ops = sig
        shape = (f"SELECT {agg + ' ' if agg else ''}<col>"
                 + (" WHERE " + " AND ".join(f"<col>{o}<v>" for o in ops) if ops else ""))
        print(f"   {100 * c / total:5.1f}%  {shape}")
    print("\n# conditions per query:",
          {k: f"{100 * v / total:.0f}%" for k, v in sorted(ncond.items())})


# --- Stage 2: the zero-generation slot-filler (NL + schema -> structured intent) -----
import re  # noqa: E402

_STOP = set("what which who whom whose where when name is are was were be been the a an "
            "of in for to do does did with by on at as from that this these those there "
            "and or how have has had show me list give tell".split())


def _toks(s: str) -> list[str]:
    return re.sub(r"[^a-z0-9 ]", " ", str(s).lower()).split()


def _detect_agg(qn: str) -> int:
    # order matters: COUNT cues first, then MAX/MIN, then SUM/AVG
    if any(w in qn for w in ("how many", "number of", "count of", "total number")):
        return 3
    if any(w in qn for w in ("maximum", "highest", "largest", "greatest", "most ",
                             "latest", "newest", "longest", "top ")):
        return 1
    if any(w in qn for w in ("minimum", "lowest", "smallest", "fewest", "least ",
                             "earliest", "oldest", "shortest")):
        return 2
    if any(w in qn for w in ("sum of", "total ")):
        return 4
    if "average" in qn or "mean " in qn:
        return 5
    return 0


def _detect_op(qn: str) -> int:
    if any(w in qn for w in ("more than", "greater than", "larger than", "after ",
                             "over ", "above ", "at least")):
        return 1  # >
    if any(w in qn for w in ("less than", "fewer than", "smaller than", "before ",
                             "under ", "below ", "at most")):
        return 2  # <
    return 0  # =


def parse(question: str, table: dict) -> dict | None:
    """Question + schema -> {sel, agg, conds}, with ZERO generated tokens. Returns None
    (abstain -> escalate) when the gate isn't confident — that is the PLG decision."""
    header = table["header"]
    qn = " " + re.sub(r"[^a-z0-9 ]", " ", question.lower()) + " "
    qtok = set(_toks(question)) - _STOP

    # conditions: a cell VALUE that appears (as a phrase) in the question -> its column.
    conds, used = [], set()
    op = _detect_op(qn)
    for col in range(len(header)):
        best_v = None
        for r in table["rows"]:
            v = str(r[col])
            vn = re.sub(r"[^a-z0-9 ]", " ", v.lower()).strip()
            if len(vn) >= 2 and f" {vn} " in qn:
                if best_v is None or len(vn) > len(best_v[1]):
                    best_v = (v, vn)
        if best_v and col not in used:
            conds.append([col, op if op and best_v[1].replace(" ", "").isdigit() else 0,
                          best_v[0]])
            used.add(col)

    # select column: best header-token overlap with the question, not already a cond col.
    best, sel = -1.0, 0
    for i, h in enumerate(header):
        score = len(qtok & (set(_toks(h)) - _STOP)) - (0.5 if i in used else 0)
        if score > best:
            best, sel = score, i

    agg = _detect_agg(qn)
    sql = {"sel": sel, "agg": agg, "conds": conds}

    # the GATE (confidence): answer only when the structure is well-grounded —
    # a select column with real overlap, a sane number of grounded conditions, and not
    # the ambiguous zero-signal case. Otherwise abstain and let a bigger model handle it.
    confident = best >= 1 and len(conds) <= 3 and (conds or agg == 3)
    return sql if confident else None


def _canon(sql: dict) -> tuple:
    return (sql["sel"], sql["agg"],
            tuple(sorted((c[0], c[1], str(c[2]).lower()) for c in sql["conds"])))


def stage2_eval(split: str = "dev") -> None:
    qs, tables = load(split)
    n = len(qs)
    em_all = 0          # exact-match if we ALWAYS answer (no gate)
    answered = correct = 0   # gated: PLG route-first path
    for q in qs:
        t = tables[q["table_id"]]
        gold = _canon(q["sql"])
        # ungated: force an answer (disable abstain) to get raw filler accuracy
        forced = parse(q["question"], t)
        if forced is None:
            # re-run without the gate to score the raw structure
            pass
        pred = parse(q["question"], t)
        # raw accuracy needs a forced parse; recompute deterministically without gate:
        raw = _force_parse(q["question"], t)
        if _canon(raw) == gold:
            em_all += 1
        if pred is not None:
            answered += 1
            if _canon(pred) == gold:
                correct += 1
    print(f"=== Stage 2 · zero-generation slot-filler  (split={split}, N={n:,}) ===")
    print(f"ungated exact-match (always answer):   {100 * em_all / n:5.1f}%")
    cov = 100 * answered / n
    prec = 100 * correct / answered if answered else 0
    print(f"GATED (PLG route-first, 0 tokens):")
    print(f"   coverage (routed, 0 tokens):        {cov:5.1f}%  ({answered:,}/{n:,})")
    print(f"   precision on routed subset:         {prec:5.1f}%  ({correct:,}/{answered:,})")
    print(f"   -> the {100 - cov:.1f}% the gate abstains on is the tail to escalate "
          "(small assembler / vector tier / LLM).")


def _force_parse(question: str, table: dict) -> dict:
    """Same as parse() but never abstains — for measuring the raw filler."""
    header = table["header"]
    qn = " " + re.sub(r"[^a-z0-9 ]", " ", question.lower()) + " "
    qtok = set(_toks(question)) - _STOP
    conds, used = [], set()
    op = _detect_op(qn)
    for col in range(len(header)):
        best_v = None
        for r in table["rows"]:
            v = str(r[col]); vn = re.sub(r"[^a-z0-9 ]", " ", v.lower()).strip()
            if len(vn) >= 2 and f" {vn} " in qn and (best_v is None or len(vn) > len(best_v[1])):
                best_v = (v, vn)
        if best_v and col not in used:
            conds.append([col, op if op and best_v[1].replace(" ", "").isdigit() else 0,
                          best_v[0]]); used.add(col)
    best, sel = -1.0, 0
    for i, h in enumerate(header):
        score = len(qtok & (set(_toks(h)) - _STOP)) - (0.5 if i in used else 0)
        if score > best:
            best, sel = score, i
    return {"sel": sel, "agg": _detect_agg(qn), "conds": conds}


# --- Stage 3: the GATE as a confidence sweep (the PLG operating curve) ---------------
def _parse_scored(question: str, table: dict) -> tuple[dict, float]:
    """Deterministic parse + a confidence the gate thresholds on. Confidence rewards a
    UNIQUE select column, SPECIFIC (long) grounded values, and FEW conditions — the
    conditions under which the 0-token filler is actually trustworthy."""
    header = table["header"]
    qn = " " + re.sub(r"[^a-z0-9 ]", " ", question.lower()) + " "
    qtok = set(_toks(question)) - _STOP
    conds, used, cond_minlen = [], set(), 99
    op = _detect_op(qn)
    for col in range(len(header)):
        best_v = None
        for r in table["rows"]:
            v = str(r[col]); vn = re.sub(r"[^a-z0-9 ]", " ", v.lower()).strip()
            if len(vn) >= 2 and f" {vn} " in qn and (best_v is None or len(vn) > len(best_v[1])):
                best_v = (v, vn)
        if best_v and col not in used:
            conds.append([col, op if op and best_v[1].replace(" ", "").isdigit() else 0,
                          best_v[0]]); used.add(col); cond_minlen = min(cond_minlen, len(best_v[1]))
    sc = sorted(((len(qtok & (set(_toks(h)) - _STOP)) - (0.5 if i in used else 0), i)
                 for i, h in enumerate(header)), reverse=True)
    best_score, sel = sc[0]
    margin = best_score - (sc[1][0] if len(sc) > 1 else 0)
    agg = _detect_agg(qn)
    conf = min(best_score, 2) + min(margin, 2)
    if conds:
        conf += min(cond_minlen, 6) / 3.0
    conf -= max(0, len(conds) - 1) * 0.8  # compounding error from many conditions
    return {"sel": sel, "agg": agg, "conds": conds}, conf


def stage3_gate_sweep(split: str = "dev") -> None:
    qs, tables = load(split)
    n = len(qs)
    rows = []
    for q in qs:
        sql, conf = _parse_scored(q["question"], tables[q["table_id"]])
        rows.append((conf, _canon(sql) == _canon(q["sql"])))
    rows.sort(reverse=True)  # most confident first
    print(f"=== Stage 3 · gate operating curve  (split={split}, N={n:,}) ===")
    print("  route the top-confidence X% at 0 tokens; escalate the rest:")
    print(f"  {'coverage':>9} {'precision@0tok':>15} {'escalate':>10}")
    for frac in (0.10, 0.25, 0.40, 0.50, 0.60, 0.75, 0.90, 1.00):
        k = max(1, int(frac * n))
        correct = sum(1 for _, ok in rows[:k] if ok)
        print(f"  {100 * k / n:7.0f}% {100 * correct / k:13.1f}% {100 * (n - k) / n:9.0f}%")
    print("\n  reading: the high-confidence head is answered cheaply and accurately; the\n"
          "  low-confidence tail is exactly what the vector tier (c_gate disambiguation)\n"
          "  or an LLM should take. The gate turns one hard problem into easy + rare-hard.")


if __name__ == "__main__":
    import sys
    stage = sys.argv[1] if len(sys.argv) > 1 else "1"
    {"1": stage1_template_mining, "2": stage2_eval, "3": stage3_gate_sweep}[stage]()
