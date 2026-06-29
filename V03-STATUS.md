# MK v03 — Layered NL→Executable Translator

**STATUS: ALL GREEN — 11 suites, 493+ rungs, 0 failures**

## Architecture

```
English intent
   │  parse()
   ▼
ASG  — 30 node types, target-independent Abstract Syntax Graph
   │  validate (fail-closed on irreversible)
   ▼
┌─────────────┬─────────────┬─────────────┬─────────────┐
│ interpreter │ terminal    │ python      │ sql         │  ← 4 pluggable backends
│ (direct)    │ backend     │ backend     │ backend     │     compiled FROM the same ASG
└─────────────┴─────────────┴─────────────┴─────────────┘
   │  execute in sandbox
   ▼
verified OS outcome
```

## Component inventory

| File | Role | Status |
|------|------|--------|
| `asg.py` | 30 ASG node types + NL parser | ✅ |
| `interpreter.py` | Direct executor (execute → str, run → stdout) | ✅ |
| `terminal_backend.py` | Shell code generator | ✅ |
| `python_backend.py` | Python code generator | ✅ |
| `sql_backend.py` | SQL code generator + executor | ✅ |
| `planner.py` | 93-rule planner/composer (compound, iteration, pipeline, vars) | ✅ |
| `council.py` | Council loop + scored conformance | ✅ |
| `run.py` | Main driver with plateau detection | ✅ |
| `mk.py` | Unified CLI (REPL + one-shot, multi-backend) | ✅ |
| `distill.py` | Embedding-based model distillation (Experiment 3) | ✅ |
| `evolve.py` | Governed self-enhancement framework (Experiment 4 design) | ✅ |
| `generate_triples.py` | 12.7K execution-verified training triples | ✅ |

## Test results (all green)

| Suite | Rungs | What it covers |
|-------|-------|----------------|
| `_verify_all.py` | 11 | v02 regression — the original council 11/11 |
| `test_v03.py` | 89 | ASG, terminal, python, sql, cross-target invariant |
| `test_planner.py` | 146 | Compound rules, conjunctions, iteration, vars |
| `test_transform.py` | 47 | Parse, exec, 4 backends, cross-target transform |
| `test_cross_backend.py` | 74 | Cross-backend equivalence (all 4 backends same output) |
| `test_cross_backend_pipeline.py` | 4 | Pipeline ops equivalent across 4 backends |
| `test_distill.py` | 30 | Embedding index, retrieval accuracy, latency |
| `test_iter_pipeline.py` | 39 | Pipeline+iteration composition (plan + e2e) |
| `test_evolve.py` | 33 | Governed self-enhancement safety boundary |
| `test_language_build.py` | 9 | Verifier integrity (scorer correctness) |
| **Total** | **493** | **ALL GREEN ✅** |

## ASG node types (30)

| Node | Type | Intents handled |
|------|------|-----------------|
| `CreateFile` | Process | create file NAME with content "TEXT" |
| `ReadFile` | Terminal | read file NAME |
| `AppendFile` | Process | append "TEXT" to NAME |
| `CountLines` | Terminal | count lines in NAME |
| `CountWords` | Terminal | count words in NAME |
| `SortLines` | Terminal | sort lines in NAME |
| `HeadLines` | Terminal | show first N lines of NAME |
| `SumNumbers` | Terminal | sum numbers in NAME |
| `ExtractPattern` | Terminal | extract lines matching "PATTERN" from NAME |
| `CopyFile` | Process | copy SRC to DEST |
| `MakeDirectory` | Process | make directory NAME |
| `MoveFile` | Process | move SRC to DEST |
| `ListFiles` | Terminal | list files [in DIR] |
| `FindFiles` | Terminal | find files containing "TEXT" |
| `DeleteFile` | Process | delete NAME [confirm] |
| `Conditional` | Decision | if NAME exists then ... otherwise ... |
| `GlobFiles` | Terminal | glob files matching "PATTERN" |
| `ForEachFile` | Decision | iterate over files, execute body per match |
| `SetVar` | Decision | set VAR = INTENT (capture output) |
| `PrintVar` | Terminal | print $VAR |
| `ReplaceText` | Terminal | replace "OLD" with "NEW" in NAME |
| `TransformCase` | Terminal | uppercase/lowercase/titlecase NAME |
| `UniqueLines` | Terminal | unique lines in NAME |
| `ReverseLines` | Terminal | reverse lines in NAME |
| `TailLines` | Terminal | show last N lines of NAME |
| `FilterLines` | Terminal | exclude lines matching "PATTERN" from NAME |
| `IfVar` | Decision | if $VAR op N then ... otherwise ... |
| `WriteFile` | Process | write "TEXT" to NAME (overwrite/create) |
| `ArithmeticExpr` | Terminal | compute EXPR (arithmetic) |
| `FileExists` | Terminal | exists NAME → yes/no |

## Planner rules (93 total)

- **42 compound rules** — backup, inspect, init project, safe delete, ensure exists, upsert, etc.
- **16 iteration rules** — "X all *.EXT" patterns (backup, count, read, inspect, delete, sort, etc.)
- **11 iteration+pipeline rules** — "for each *.EXT, count lines and append to SUMMARY" patterns with pre-step initialization
- **5 variable binding rules** — set/capture/print variable patterns
- **19 pipeline/conjunction rules** — sequential composition, conjunction splitting
- LLM fallback (Ollama) for novel compound intents

## Experiment timeline

| Exp | What | Result | Status |
|-----|------|--------|--------|
| **Exp 1** | Council loop — 5 models build NL→OS interpreter by anonymous consensus | **11/11** (220 rounds, claude-sonnet-4 won) | ✅ Complete |
| **Exp 2** | Governed self-enhancement — enforcer/developer loop on throwaway clone | Design complete, safety boundary tested (33 rungs) | ✅ Design + tests |
| **Exp 3** | Model distillation — embedding index replaces LLM for routing | 79.7% top-1, 86% top-3, 40000× faster (0.05ms vs 2s) | ✅ Complete |
| **Exp 4** | Governed self-enhancement — actual evolution loop | Design in EXP2-DESIGN.md, test infrastructure ready | 🔜 Next |

### Experiment 3 — distillation results

| Metric | Value |
|--------|-------|
| Embedding index | 2,527 vectors (768-dim, nomic-embed-text) |
| Training triples | 12,729 execution-verified instances |
| Accuracy top-1 | 79.7% |
| Accuracy top-3 | 86.0% |
| Accuracy top-5 | 88.0% |
| Latency (retrieval) | 0.05ms |
| Latency (LLM baseline) | 2000ms+ |
| Speedup | ~40,000× |
| Perfect templates | count-lines, count-words, find-content, mkdir-move-list, sum-numbers |

## Data pipeline

`generate_triples.py` produces execution-verified triples across 17 templates × 4 backends:

| Axis | Value |
|------|-------|
| Total candidate instances | ~12,700 |
| Backends verified per triple | 3–4 |
| Total triples in `triples.jsonl` | 12,729 |
| Embedding index vectors | 2,527 (deduplicated) |
