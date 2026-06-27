# MK · SQL cell — findings (PLG on WikiSQL)

Honest, measured. Code: `mk_sql.py` (`python mk_sql.py 1|2|3`). Data: cached WikiSQL
(80,654 queries, train+dev+test). No tuning to the test set; dev used for Stage 2/3.

## Stage 1 — template mining (PLG's central claim) ✅ STRONG
- 80,654 queries → **488 distinct structural templates** (agg × condition-ops shape).
- **1 template covers 53.1%** (`SELECT <col> WHERE <col>=<v>`); **9 cover 80%**, 28→90%,
  62→95%, 183→99%.
- Conditions/query: 0:1% · 1:69% · 2:24% · 3:5% · 4:1%.
- **Verdict:** the SQL *shape* is near-zero-entropy. "Generation" of structure is really
  routing over a handful of patterns — PLG confirmed at the structural level. Assembly
  (structure → SQL string) is pure slot-fill, 0 tokens.

## Stage 2 — zero-generation slot-filler (NL + schema → structure) ⚠️ CEILING
- Naive deterministic filler (lexical: agg keywords, header-token overlap for SELECT,
  cell-value substring match for WHERE): **42.5% exact-match** (always-answer).
- That's in the historical range for rule-based WikiSQL — the structure is free, but the
  **value-grounding is the hard part**: *which* column is asked, *which* cell is the
  condition value.

## Stage 3 — the gate (confidence sweep) ⚠️ DIRECTIONAL, WEAK
Confidence = select-column uniqueness + value specificity − condition count.
Route the top-confidence X% at 0 tokens; escalate the rest:

| coverage | precision @ 0 tokens |
|---:|---:|
| 10% | 67.2% |
| 25% | **72.1%** (peak) |
| 50% | 61.2% |
| 100% | 42.4% |

- The confidence signal **does** correlate with correctness (72% vs 42% baseline), so the
  gate idea is sound — but lexical features are a **weak** predictor (even the top 10% is
  only 67% right). A clean PLG gate (route 80% @ ≥95%) is NOT reachable with token overlap.

## The conclusion (where the bits actually are)
- **Structure: retrievable** (Stage 1). The skeleton needs no generation.
- **Grounding: semantic** (Stage 2/3). Knowing the question "position" → the `Position`
  column, or that "butler cc (ks)" is a `School/Club Team` value, is a **similarity**
  problem that literal token/substring matching can't solve well. This is the ceiling.
- **This is exactly the `c_gate` job.** Replace lexical select/value matching with
  **embedding similarity** between the question and (column names, cell values) on the
  compressed context manifold — `c_gate` (relevance-weight) → `c_bit` (collapse to the
  chosen column/value). The next experiment: re-run Stage 2/3 with semantic grounding and
  measure whether the gate's precision/coverage frontier lifts. That is the
  context-computing ↔ MK fusion, made measurable.

## Stage 4 — c_gate substitution (MK ↔ context-computing) ❌ NEGATIVE (robust)
Hypothesis: replace lexical SELECT-column choice with embedding similarity
(question ↔ column name), i.e. `c_gate` (relevance-weight) → `c_bit` (argmax). Embeddings:
local Ollama `nomic-embed-text`. conds/agg held identical, so the delta isolates SELECT.
Code: `mk_sql_cgate.py`. Measured on a 300-query dev slice (lexical baseline 41.3% on it):

| variant | ungated exact-match | vs lexical |
|---|---:|---:|
| lexical (baseline) | 41.3% | — |
| c_gate, whole question | 25.3% | **−16.0** |
| c_gate, residual (cond spans stripped) | 26.7% | −14.7 |
| hybrid (lexical, c_gate fallback on the ambiguous tail) | 34.7% | −6.7 |

On the lexically-ambiguous tail (58% of queries) the embedding fallback **broke 20 more
SELECTs than it fixed** (net −20). Off-the-shelf dense cosine is *worse* than lexical, even
as a fallback.

**Why (the real lesson):** WikiSQL questions usually **echo the column name literally**
("What **position**…"), so lexical exact-match is a strong, high-precision signal; generic
sentence-embedding cosine just adds noise. And naive cosine is **not** what the
context-computing project means by `c_gate` — that is β-sharpened relevance re-weighting on
a **low-rank manifold**, and its headline result was that a **learned** `c_byte`
(manifold projection) beats the raw mean. Raw cosine is the degenerate version.

**Verdict:** the MK ↔ context-computing fusion is **not** "swap in off-the-shelf
embeddings." If `c_gate` is to help schema-linking it needs either (a) **schema-aware
representations** — embed each column as `name + sample cell values`, since the question
often identifies the column via its *values*, not its name — or (b) the project's actual
**learned low-rank operator**, not generic nomic cosine. Untested; the next hypothesis.

## Pitfalls logged
- Lexical confidence is a weak gate; don't tune regex further — the fix is semantic.
- **But** naive dense embeddings don't beat lexical for WikiSQL schema-linking (Stage 4).
  Lexical echoing is a strong baseline; "add embeddings" is not free progress. Need
  schema-aware reps or the learned operator, measured against the 41.3% / 70%@25% baseline.
