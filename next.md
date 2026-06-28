# Next Steps — v03 and beyond

> Working memory for what is actionable now. Updated post-pipeline-scaling.

## Completed

- NL->SQL backend: Done. sql_backend.py compiles ASG->SQL (SQLite). 21 rungs added. 4th backend.
- Scale the data pipeline: Done (v2). 40 filenames, 45 short contents, 24 number sets, 17 templates, ~12.7K candidate instances. SQL added as 4th verification backend.
- Wire scored conformance: Done. 5-tier gradient scoring through council.py + run.py.

Current state: 89/89 rungs green, ~12.7K candidate triples, 16 ASG node types, 4 backends, 0 regressions.

## Now (immediate, high-leverage)

### 1. Run a live experiment cycle with the gradient
- Action: Start Ollama, execute council build rounds using run.py, observe gradient dynamics.
- Blocker: Requires Ollama running (not available in current session).

### 2. Model distillation: train specialist translators
- Action: Fine-tune small models from triples.jsonl for NL->shell, NL->Python, NL->SQL.

## Next (medium-term)

### 3. The planner/composer
- A reasoning agent over the translation organs.

## Later (ambitious)

### 4. Experiment 2: governed self-enhancement
- Build the ENFORCER/DEVELOPER loop from EXP2-DESIGN.md.

## Boundaries (protected files)
- _verify_all.py, interpreter.v02.py, CAPABILITIES.v02.md, CAPABILITIES.prev.md
- dump.log, rounds/, OBSERVATIONS.md, SPEC.md, EXP2-DESIGN.md, VISION.md
