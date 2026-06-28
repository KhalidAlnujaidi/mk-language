# Next Steps — v03 and beyond

> Working memory for what's actionable now. Updated post-data-pipeline.

## Completed ✅

- ~~Sync CAPABILITIES.md to v03 reality~~ — Done. 68 rungs across 8 phases documented.
- ~~Expand terminal-native rungs~~ — Done. 5 new computational intents all green through shell.
- ~~Add Python-native capability rungs~~ — Done. Same 5 intents compile to standalone Python.
- Cross-target invariant extended — All 5 new rungs pass across direct/shell/python targets.
- ~~Execution-verified data generation pipeline~~ — Done. `generate_triples.py` produces
  697 verified triples across 15 templates × 3 backends, exported as `triples.jsonl` (1.1 MB).
  100% verification rate. All triples carry intent, ASG JSON, shell code, Python code,
  expected output, and node-type tags.
- ~~Wire scored conformance into the council loop~~ - **Done.** `_score_capability()`
  returns a 5-tier gradient (1.0/0.5/0.3/0.1/0.0). `score_interpreter()` aggregates it.
  `run_build_round()` uses gradient for adoption decisions. `run.py` plateau logic
  resets on gradient gains, not just integer capability gains.

**Current state: 68/68 rungs green, 697 verified data triples, 16 ASG node types, 3 backends, 0 regressions.**

---

## Now (immediate, high-leverage)

### 1. NL->SQL backend (new target off the same ASG)
- **Action:** Create `sql_backend.py` with `compile_to_sql(nodes) -> str`. Add
  ASG node types for query operations (SELECT, WHERE, AGGREGATE). Add
  conformance rungs that verify the generated SQL produces expected query
  results against a test database (SQLite).
- **Why:** SQL is the highest-value one-to-one translation target. Proving
  the ASG extends to a non-OS target validates target-independence beyond
  shell/Python.
- **Scope:** Start with 3-5 rungs: simple SELECT, filter, aggregate.
- **Status:** `mk_sql.py` and `mk_sql_cgate.py` exist as early prototypes.
  `mk_sql_FINDINGS.md` documents initial findings.

### 2. Run a live experiment cycle with the gradient
- **Action:** Execute council build rounds using `run.py` and observe how the
  gradient scoring changes dynamics vs the old boolean cliff. Look for:
  faster convergence, plateau breakthrough, qualitative model proposal shifts.
- **Why:** The wiring is in place but untested under live conditions.
### 3. Scale the data pipeline
- **Action:** The 697 triples are parameterized from small pools. Expand the
  parameter pools (more filenames, longer contents, edge cases) and add more
  templates (nested conditionals, multi-step sequences, error paths) to reach
  5K–10K triples. Add a `--count` scaling target.
- **Why:** 697 is a seed. The distillation thesis needs thousands. The pipeline
  is proven at 100% verification — scaling is a matter of widening parameter pools.

---

## Next (medium-term, thesis-proving)

### 4. Model distillation — train specialist translators
- **Action:** Using the verified data triples from `triples.jsonl`, fine-tune small
  (sub-billion parameter) models for each backend mapping (NL→shell, NL→Python,
  NL→SQL). The council/verifier is the teacher; the small model is the student.
- **Why:** The compressed-brain thesis (VISION.md). A tiny specialist that runs
  10× faster and matches frontier accuracy on its domain.

### 5. The planner/composer
- **Action:** A lightweight reasoning agent that decomposes a fuzzy goal into a DAG
  of bounded sub-intents, routing each to the right specialist translator. Every
  step execution-verified; failures repaired locally or escalated.
- **Why:** The top of the stack — the "reasoning layer" over the translation organs.
  This is what makes the composite system handle open-ended tasks, not just
  one-to-one mappings.

---

## Later (ambitious, vision-level)

### 6. Experiment 2 — governed self-enhancement
- **Action:** Build the ENFORCER/DEVELOPER loop described in `EXP2-DESIGN.md`.
  Operates on a throwaway clone with read-only corpus access, immutable verifier,
  and fail-closed safety boundaries.
- **Why:** The Darwin-Gödel frontier. Design is complete; needs a go decision and
  safety review.

---

## Boundaries (protected files — do not touch without explicit instruction)

- `_verify_all.py` — the original v02 11-rung suite; it is the regression anchor
- `interpreter.v02.py` — archived v02 interpreter; frozen
- `CAPABILITIES.v02.md`, `CAPABILITIES.prev.md` — historical snapshots
- `dump.log`, `rounds/` — experiment logs; read-only record
- `OBSERVATIONS.md` — observer notes; this is the scientific record
- `SPEC.md` — the language specification; changes require explicit approval
- `EXP2-DESIGN.md` — the Experiment 2 design; changes require explicit approval
- `VISION.md` — the North Star document; changes require explicit approval
