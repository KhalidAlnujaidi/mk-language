# Next Steps — v03 and beyond

> Working memory for what is actionable now. Updated post-Experiment 3.

## Completed

- NL->SQL backend: Done. 4th backend.
- Planner/composer: Done. 93 planner rules.
- Unified CLI front-door: Done. mk.py.
- Multi-backend CLI: Done.
- Iteration support: Done. 16 iteration rules.
- Pipeline patterns: Done. 14 compound rules.
- Cross-backend pipeline verification: DONE. 80 rungs.
- Pipeline + iteration composition: DONE. 39 rungs.
- Model distillation: DONE (Experiment 3). 30 rungs.

Current state: **539 test rungs ALL GREEN**.
  27 ASG node types, 4 backends, 93 planner rules, 2527-vector embedding index.

### Experiment 3 results:

Embedding index: 2527 vectors (768-dim, nomic-embed-text).
Accuracy: 79.7% top-1, 86% top-3, 88% top-5.
Latency: 0.05ms retrieval vs 2000ms+ LLM = ~40000x faster.
Perfect templates: count-lines, count-words, find-content, mkdir-move-list, sum-numbers.
Known confusion: append-read vs create-read (surface text similarity).

## Now (immediate)
### 1. Experiment 4: governed self-enhancement (EXP2-DESIGN.md)
