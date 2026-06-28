# Next Steps — v03 and beyond

> Working memory for what is actionable now. Updated post-iteration-support.

## Completed

- NL->SQL backend: Done. sql_backend.py compiles ASG->SQL (SQLite). 21 rungs added. 4th backend.
- Scale the data pipeline: Done (v2). ~12.7K candidate instances. SQL added as 4th verification backend.
- Wire scored conformance: Done. 5-tier gradient scoring through council.py + run.py.
- Planner/composer: Done. 37 compound rules, conjunction splitting, Ollama LLM fallback.
- Unified CLI front-door: Done. mk.py — one-shot + REPL mode.
- Multi-backend CLI: Done. --backend shell/python/sql, --show-all.
- Iteration support: Done. 2 new ASG node types (GlobFiles + ForEachFile).
  7 iteration planner rules. All 4 backends handle iteration. 30 new test rungs.

Current state: 89/89 v03 rungs, 128/128 planner rungs green.
Total: 217 rungs. 20 ASG node types, 4 backends, 42 compound + 7 iteration + 5 var planner rules.

- Variable binding: Done. 2 new ASG node types (SetVar + PrintVar).
  {var} substitution across all backends. 5 planner rules. 17 new test rungs.

## Now (immediate, high-leverage)

### 1. Model distillation: train specialist translators
- Fine-tune small models from triples.jsonl for NL->shell, NL->Python, NL->SQL.
- ~12.7K verified triples.

### 2. Wire iteration into mk.py CLI
- Add REPL support for "backup all *.txt" etc.
- Show ForEachFile plans in :plan output.

### 3. Expand iteration patterns
- "compress all .log files", "find all files larger than N", nested iteration.

## Next (medium-term)

### 4. Variable binding and data-dependent branching
- Output capture from Terminal nodes and substitution into later nodes.

### 5. Wire the planner into the council loop

## Later (ambitious)

### 6. Experiment 2: governed self-enhancement
- Build the ENFORCER/DEVELOPER loop from EXP2-DESIGN.md.
