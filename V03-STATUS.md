# MK v03 — Layered NL→Executable Translator

**STATUS: ALL PHASES GREEN — 89/89 v03 + 128/128 planner + 47/47 transform + 11/11 v02 = 275 rungs pass**

## What changed (v02 → v03)

v02 was a flat interpreter: `English → regex match → OS call` (direct, hard-wired, one target).

v03 introduces the ASG intermediate layer:

```
English intent
   │  parse()
   ▼
ASG  — target-independent Abstract Syntax Graph
   │  validate (fail-closed on irreversible)
   ▼
┌─────────────┬─────────────┬─────────────┬─────────────┐
│ interpreter │ terminal    │ python      │ sql         │  ← pluggable backends
│ (direct)    │ backend     │ backend     │ backend     │     compiled FROM the same ASG
└─────────────┴─────────────┴─────────────┴─────────────┘
   │  execute in sandbox
   ▼
verified OS outcome
```

Add a new target = add one backend. No change to the parser or existing backends.

## Architecture

| File | Role |
|------|------|
| `asg.py` | ASG node dataclasses (24 types) + NL parser (`parse(source) → [nodes]`) |
| `interpreter.py` | Direct executor (`execute(nodes) → str`, `run(source) → stdout`) |
| `terminal_backend.py` | Shell code generator (`compile_to_shell(nodes) → str`) |
| `python_backend.py` | Python code generator (`compile_to_python(nodes) → str`) |
| `sql_backend.py` | SQL code generator + executor (`compile_to_sql`, `execute_sql(nodes) → str`) |
| `planner.py` | Planner/composer — compound rules, conjunction splitting, LLM fallback |
| `council.py` | Council loop + scored conformance (`_score_capability`, `score_interpreter`, `run_build_round`) |
| `run.py` | Main driver — gradient-aware plateau detection, fractional score feedback to models |
| `mk.py` | Unified CLI front-door — REPL + one-shot, multi-backend |
| `test_v03.py` | Full test suite: ASG, terminal, python, sql, cross-target, scored conformance (89 rungs) |
| `test_planner.py` | Planner test suite (128 rungs) |
| `test_transform.py` | Text transformation tests (47 rungs) |
| `_verify_all.py` | Original v02 11-rung conformance suite (unchanged, still 11/11) |

## ASG node inventory (24 types)

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

## Test results

```
test_v03.py:       89 rungs — ASG, terminal, python, sql, cross-target     ✅
test_planner.py:  128 rungs — compound rules, conjunctions, iteration, vars ✅
test_transform.py: 47 rungs — parse, exec, 4 backends, cross-target          ✅
_verify_all.py:    11 rungs — v02 regression                                ✅
Total:            275 rungs, ALL GREEN
```

## Data pipeline (v2 — scaled)

`generate_triples.py` produces execution-verified triples across 17 templates × 4 backends:

| Axis | v1 (original) | v2 (scaled) |
|------|---------------|-------------|
| Total candidate instances | 697 | ~12,700 |
| Backends verified per triple | 3 | 3 or 4 (SQL added where applicable) |
