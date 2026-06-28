# Next Steps — v03 and beyond

> Working memory for what is actionable now. Updated post-planner.

## Completed

- NL->SQL backend: Done. sql_backend.py compiles ASG->SQL (SQLite). 21 rungs added. 4th backend.
- Scale the data pipeline: Done (v2). 40 filenames, 45 short contents, 24 number sets, 17 templates, ~12.7K candidate instances. SQL added as 4th verification backend.
- Wire scored conformance: Done. 5-tier gradient scoring through council.py + run.py.
- Planner/composer: Done. planner.py decomposes complex NL into ASG-parseable steps.
  46 test rungs (deterministic + conjunction + passthrough + e2e + LLM integration).
  17 compound rules, conjunction splitting, Ollama LLM fallback.

Current state: 89/89 v03 rungs green, 11/11 v02 rungs green, 46/46 planner rungs green.
16 ASG node types, 4 backends, planner/composer with deterministic + LLM decomposition.

## Now (immediate, high-leverage)

### 1. Expand planner compound rules + test with more complex NL
- Action: Add more deterministic decomposition patterns (conditional compound,
  iterative patterns, multi-file batch operations).
- Add planner rungs to the main test_v03.py suite.
- Test the LLM fallback against harder novel requests (multi-sentence descriptions).

### 2. Model distillation: train specialist translators
- Action: Fine-tune small models from triples.jsonl for NL->shell, NL->Python, NL->SQL.
- The data pipeline now produces ~12.7K verified triples — enough for fine-tuning.

## Next (medium-term)

### 3. Wire the planner into the council loop
- The planner can serve as a pre-processor: complex NL -> planner -> simple NL lines ->
  council interpreter. This would let the council handle multi-step compound intents.

### 4. The planner as a reasoning agent
- Extend the planner to handle truly complex requests that require conditional logic,
  loops, or data-dependent branching (beyond what deterministic rules can express).

## Later (ambitious)

### 5. Experiment 2: governed self-enhancement
- Build the ENFORCER/DEVELOPER loop from EXP2-DESIGN.md.

## Boundaries (protected files)
- _verify_all.py, interpreter.v02.py, CAPABILITIES.v02.md, CAPABILITIES.prev.md
- dump.log, rounds/, OBSERVATIONS.md, SPEC.md, EXP2-DESIGN.md, VISION.md
