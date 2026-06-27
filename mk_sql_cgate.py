"""MK · SQL cell — the c_gate substitution (MK <-> context-computing fusion, measured).

Stage 2/3 found the ceiling is SEMANTIC grounding: lexical token-overlap can't tell that
"position" -> the `Position` column. This swaps the SELECT-column choice from lexical
overlap to EMBEDDING SIMILARITY between the question and each column name — i.e. c_gate
(relevance-weight the columns by relevance to the question) -> c_bit (collapse to argmax).
Everything else (conds, agg) is held IDENTICAL to the lexical baseline, so the measured
delta isolates the c_gate effect. Embeddings: local Ollama nomic-embed-text.

Run:  python mk_sql_cgate.py [N]     (N = dev slice size, default 2000)
"""

from __future__ import annotations

import hashlib
import math
import pickle
import re
from pathlib import Path

import httpx

import mk_sql as M

EMB_MODEL = "nomic-embed-text"
EMB_URL = "http://127.0.0.1:11434/api/embed"
CACHE = Path(__file__).resolve().parent / ".emb_cache_nomic.pkl"
_cache: dict[str, list] = pickle.loads(CACHE.read_bytes()) if CACHE.exists() else {}


def _key(t: str) -> str:
    return hashlib.sha1(t.encode("utf-8")).hexdigest()


def embed_many(texts: list[str]) -> dict[str, list]:
    """Embed (with disk cache). Batches the cache-misses through Ollama /api/embed.
    Returns L2-normalized vectors (so a dot product is cosine)."""
    uniq = list(dict.fromkeys(texts))
    miss = [t for t in uniq if _key(t) not in _cache]
    for i in range(0, len(miss), 64):
        batch = miss[i:i + 64]
        r = httpx.post(EMB_URL, json={"model": EMB_MODEL, "input": batch}, timeout=120)
        r.raise_for_status()
        for t, e in zip(batch, r.json()["embeddings"]):
            _cache[_key(t)] = e
    if miss:
        CACHE.write_bytes(pickle.dumps(_cache))
    out = {}
    for t in uniq:
        v = _cache[_key(t)]
        n = math.sqrt(sum(x * x for x in v)) or 1.0
        out[t] = [x / n for x in v]
    return out


def _dot(a: list, b: list) -> float:
    return sum(x * y for x, y in zip(a, b))


def _residual(question: str, table: dict) -> str:
    """The question with its matched condition VALUES stripped — so what remains points
    at the SELECT target, not the WHERE filter. (Decompose, THEN gate.)"""
    conds, _, _ = _lex_conds(question, table)
    r = question
    for c in conds:
        r = re.sub(re.escape(str(c[2])), " ", r, flags=re.IGNORECASE)
    return r.strip() or question


def _lex_conds(question: str, table: dict):
    """The lexical condition finder, identical to the baseline (held fixed)."""
    header = table["header"]
    qn = " " + re.sub(r"[^a-z0-9 ]", " ", question.lower()) + " "
    conds, used, minlen = [], set(), 99
    op = M._detect_op(qn)
    for col in range(len(header)):
        best_v = None
        for r in table["rows"]:
            v = str(r[col]); vn = re.sub(r"[^a-z0-9 ]", " ", v.lower()).strip()
            if len(vn) >= 2 and f" {vn} " in qn and (best_v is None or len(vn) > len(best_v[1])):
                best_v = (v, vn)
        if best_v and col not in used:
            conds.append([col, op if op and best_v[1].replace(" ", "").isdigit() else 0,
                          best_v[0]]); used.add(col); minlen = min(minlen, len(best_v[1]))
    return conds, used, minlen


def hybrid_parse(q: dict, table: dict, qemb: list,
                 colembs: list[list]) -> tuple[dict, float, str]:
    """SELECT via PLG-recursion: take the LEXICAL column when there's a clear literal
    winner (cheap, high-precision — questions usually echo the column name); fall back to
    c_gate (cosine residual↔column → c_bit argmax) ONLY when lexical is absent or tied.
    conds/agg held identical to baseline. Returns (sql, confidence, route)."""
    question = q["question"]
    header = table["header"]
    conds, used, minlen = _lex_conds(question, table)
    qtok = set(M._toks(question)) - M._STOP
    lex = [len(qtok & (set(M._toks(h)) - M._STOP)) - (0.5 if i in used else 0)
           for i in range(len(header)) for h in [header[i]]]
    olex = sorted(range(len(header)), key=lambda i: -lex[i])
    best_lex = lex[olex[0]]
    margin_lex = best_lex - (lex[olex[1]] if len(header) > 1 else 0)
    if best_lex >= 1 and margin_lex >= 1:                  # lexical is confident -> use it
        sel, route = olex[0], "lex"
        conf = min(best_lex, 2) + min(margin_lex, 2)
    else:                                                   # lexical ambiguous -> c_gate
        sims = [_dot(qemb, ce) for ce in colembs]
        osim = sorted(range(len(sims)), key=lambda i: -sims[i])
        sel = int(next((c for c in osim if c not in used), osim[0]))
        route = "emb"
        conf = (sims[osim[0]] - (sims[osim[1]] if len(osim) > 1 else 0)) * 4
    if conds:
        conf += min(minlen, 6) / 3
    conf -= max(0, len(conds) - 1) * 0.8
    agg = M._detect_agg(" " + question.lower() + " ")
    return {"sel": sel, "agg": agg, "conds": conds}, conf, route


def run(n: int = 2000) -> None:
    qs, tables = M.load("dev")
    qs = qs[:n]
    # embed RESIDUAL questions (condition spans stripped) + all column names (cached)
    resid = {q["question"]: _residual(q["question"], tables[q["table_id"]]) for q in qs}
    cols_needed = {h for q in qs for h in tables[q["table_id"]]["header"]}
    E = embed_many(list(resid.values()) + sorted(cols_needed))

    lex_rows, sem_rows = [], []
    lex_em = sem_em = 0
    n_emb = emb_helped = emb_total = 0
    for q in qs:
        t = tables[q["table_id"]]
        gold = M._canon(q["sql"])
        # lexical baseline (same conds/agg, lexical SELECT)
        lex = M._force_parse(q["question"], t)
        ok_lex = M._canon(lex) == gold
        lex_em += ok_lex
        _, lconf = M._parse_scored(q["question"], t)
        lex_rows.append((lconf, ok_lex))
        # hybrid (lexical, c_gate fallback only when lexical is ambiguous)
        sql, sconf, route = hybrid_parse(q, t, E[resid[q["question"]]],
                                         [E[h] for h in t["header"]])
        ok_sem = M._canon(sql) == gold
        sem_em += ok_sem
        sem_rows.append((sconf, ok_sem))
        if route == "emb":            # measure the fallback in isolation
            n_emb += 1
            emb_total += 1
            emb_helped += (ok_sem and not ok_lex) - (ok_lex and not ok_sem)

    def curve(rows):
        rows = sorted(rows, reverse=True)
        out = {}
        for frac in (0.25, 0.50, 0.75):
            k = max(1, int(frac * len(rows)))
            out[frac] = 100 * sum(ok for _, ok in rows[:k]) / k
        return out

    lc, scv = curve(lex_rows), curve(sem_rows)
    print(f"=== hybrid (lexical + c_gate fallback) vs lexical  (dev slice N={len(qs):,}, "
          f"emb={EMB_MODEL}) ===")
    print(f"ungated exact-match:   lexical {100 * lex_em / len(qs):5.1f}%   ->   "
          f"hybrid {100 * sem_em / len(qs):5.1f}%   "
          f"(Δ {100 * (sem_em - lex_em) / len(qs):+.1f} pts)")
    print(f"c_gate fallback fired on {n_emb} of {len(qs)} queries "
          f"({100 * n_emb / len(qs):.0f}% — the lexically-ambiguous tail); "
          f"net SELECTs fixed−broken: {emb_helped:+d}")
    print("gated precision @ coverage (route top-confidence at 0 tokens):")
    print(f"  {'coverage':>9} {'lexical':>9} {'c_gate':>9}")
    for frac in (0.25, 0.50, 0.75):
        print(f"  {int(frac * 100):>8}% {lc[frac]:>8.1f}% {scv[frac]:>8.1f}%")


if __name__ == "__main__":
    import sys
    run(int(sys.argv[1]) if len(sys.argv) > 1 else 2000)
