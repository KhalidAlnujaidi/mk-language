# Next Steps — v03 and beyond

> Working memory for what is actionable now. Updated post-unified-CLI.

## Completed

- NL->SQL backend: Done. sql_backend.py compiles ASG->SQL (SQLite). 21 rungs added. 4th backend.
- Scale the data pipeline: Done (v2). 40 filenames, 45 short contents, 24 number sets, 17 templates, ~12.7K candidate instances. SQL added as 4th verification backend.
- Wire scored conformance: Done. 5-tier gradient scoring through council.py + run.py.
- Planner/composer: Done. planner.py decomposes complex NL into ASG-parseable steps.
  82 test rungs (deterministic + conjunction + passthrough + e2e + LLM integration + new rules + CLI).
  37 compound rules, conjunction splitting, Ollama LLM fallback.
- Unified CLI front-door: Done. mk.py — one-shot + REPL mode. Full pipeline NL->Planner->ASG->Interpreter.

Current state: 89/89 v03 rungs, 11/11 v02 rungs, 82/82 planner rungs green.
Total: 182 rungs. 16 ASG node types, 4 backends, 37 compound planner rules, unified CLI.

## Now (immediate, high-leverage)

### 1. Model distillation: train specialist translators
- Fine-tune small models from triples.jsonl for NL->shell, NL->Python, NL->SQL.
- ~12.7K verified triples — enough for fine-tuning.
- Format: {nl_intent, ast_or_asg, target_code} triples -> LoRA fine-tune a 7B model.

### 2. Multi-backend CLI: mk.py backend selection
- Add: mk.py --backend python "create file x with content hello"
  -> shows what Python code WOULD be generated
- Add: mk.py --backend sql "count lines in data.txt"
  -> shows what SQL query WOULD be generated
- Makes the multi-backend architecture visible/demonstrable.

### 3. Add planner rungs to the main test_v03.py suite
- Fold a representative subset into the main suite so there is one test command.

## Next (medium-term)

### 4. The planner as a reasoning agent
- Handle complex requests requiring loops, data-dependent branching.
- E.g. "compress all .log files" requires listing, filtering, iterating.

### 5. Wire the planner into the council loop
- Planner as pre-processor for council interpreter.

## Later (ambitious)

### 6. Experiment 2: governed self-enhancement
- Build the ENFORCER/DEVELOPER loop from EXP2-DESIGN.md.

## Boundaries (protected files)
- _verify_all.py, interpreter.v02.py, CAPABILITIES.v02.md, CAPABILITIES.prev.md
- dump.log, rounds/, OBSERVATIONS.md, SPEC.md, EXP2-DESIGN.md, VISION.md
