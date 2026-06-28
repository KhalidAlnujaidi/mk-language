# MK v03 — Layered NL→Executable Translator

**STATUS: ALL PHASES GREEN — 89/89 rungs pass**

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
| `asg.py` | ASG node dataclasses (16 types) + NL parser (`parse(source) → [nodes]`) |
| `interpreter.py` | Direct executor (`execute(nodes) → str`, `run(source) → stdout`) |
| `terminal_backend.py` | Shell code generator (`compile_to_shell(nodes) → str`) |
| `python_backend.py` | Python code generator (`compile_to_python(nodes) → str`) |
| `sql_backend.py` | SQL code generator + executor (`compile_to_sql`, `execute_sql(nodes) → str`) |
| `council.py` | Council loop + scored conformance (`_score_capability`, `score_interpreter`, `run_build_round`) |
| `run.py` | Main driver — gradient-aware plateau detection, fractional score feedback to models |
| `test_v03.py` | Full test suite: ASG, terminal, python, sql, cross-target, scored conformance (89 rungs) |
| `_verify_all.py` | Original v02 11-rung conformance suite (unchanged, still 11/11) |
| `interpreter.v02.py` | Archived v02 interpreter (flat, no ASG) |
| `generate_triples.py` | Execution-verified data pipeline (17 templates, 4 backends, ~12.7K candidate triples) |
| `triples.jsonl` | Generated triples data (verified subset exported) |

## Test results (89 rungs)

```
Phase A:  ASG Parse → Execute           11/11  (100%)  ✅
Phase A+: ASG Structure Validation        7/7   (100%)  ✅
Phase B:  Terminal Backend (ASG→Shell)   13/13  (100%)  ✅  (11 original + 2 terminal-native)
Phase B+: Terminal-Native Compute          5/5   (100%)  ✅  (wc, sort, head, sum, grep)
Phase C:  Python Backend (ASG→Python)    11/11  (100%)  ✅
Phase C+: Python-Native Compute            5/5   (100%)  ✅  (same intents, Python codegen)
Phase D:  Cross-Target Invariant         11/11  (100%)  ✅  (same intent → same OS outcome across 3 targets)
Phase D+: Cross-Target Compute Invariant   5/5   (100%)  ✅  (new compute intents, all 3 targets agree)
Phase E:  SQL Backend (ASG→SQL→SQLite)   11/11  (100%)  ✅
Phase E+: SQL-Native Compute               5/5   (100%)  ✅  (same compute intents through SQL)
Phase F:  Cross-Target Invariant (SQL)     5/5   (100%)  ✅  (SQL output matches direct execution)
```

Run tests: `python3 test_v03.py`
Run v02 regression: `python3 _verify_all.py`

## ASG node inventory (16 types)

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

## Key engineering decisions

### ASG design (asg.py)
- Core structured-intent unit: 16 frozen dataclasses, each with `node_type ∈ {Process, Terminal, Decision}`
- Decision nodes (`Conditional`) carry sub-graphs (`then_branch`, `else_branch` as node lists)
- `parse_line()` uses ordered regex matching — `delete X confirm` is checked before `delete X`

### Terminal backend (terminal_backend.py)
- `count_lines`: uses `awk 'END{print NR}'` not `wc -l` — wc undercounts files without trailing newlines (the exact bug that caused v02's 119-round plateau)
- `sum_numbers`: uses `grep -oE '[0-9]+' | awk` to extract and sum all integers
- `create_file`: guards with `[ -e ]` check, refuses overwrite
- `find_files`: loops with `grep -q` per file, not `grep -rl` (matches interpreter's file-by-file scan)
- All user input `shlex.quote`'d — injection-proof by construction

### Python backend (python_backend.py)
- Generates standalone Python source code (not executes — the interpreter does that)
- Generated code uses `repr()` for all literals — safe against injection
- Includes `if __name__ == "__main__": main()` — generated code is independently runnable

### SQL backend (sql_backend.py)
- File → Table mapping uses double-quoted identifiers: `notes.txt` → table `"notes.txt"`
  (SQLite supports quoted identifiers, so file names map 1:1 — dots preserved)
- In-memory SQLite for execution: `execute_sql(nodes)` runs the compiled SQL and returns output
- `SumNumbers` handled in Python executor (SQLite lacks regex extraction)
- Safety model matches interpreter: fail-CLOSED on delete without confirm, refuse overwrite
- **Known limitation**: directory operations (mkdir + move-to-dir + list-in-dir) have no SQL
  equivalent. The data pipeline marks `mkdir-move-list` as SQL-incompatible and verifies it
  through 3 backends (direct/shell/python) instead of 4.

### Scored conformance (council.py + run.py)
- **5-tier scoring** in `_score_capability` (council.py): 1.0 (exact), 0.5 (near-miss), 0.3 (crash), 0.1 (empty/timeout), 0.0 (no code)
- `score_interpreter` aggregates per-capability scores into a gradient dict
- `run_build_round` adopts proposals on gradient improvement, not just integer capability gains
- `run.py` plateau detection resets `stall_count` on gradient gains (`score_gain > 1e-9`), not just new full PASSes
- Models see fractional scores + reason strings in their build prompts
- `write_capabilities` displays both integer count and gradient: `"3/11 capabilities pass (gradient score: 7.5/11)"`

## Data pipeline (v2 — scaled)

`generate_triples.py` produces execution-verified triples across 17 templates × 4 backends:

| Axis | v1 (original) | v2 (scaled) |
|------|---------------|-------------|
| Filenames | 10 | 40 |
| Short contents | 10 | 45 |
| Multi-word contents | 7 | 20 |
| Number sets | 8 | 24 |
| Sortable sets | 4 | 12 |
| Line sets | 4 | 15 |
| Log sets | 4 | 12 |
| Patterns | 4 | 8 |
| Move dirs | 5 | 8 |
| Head counts | 3 | 5 |
| Templates | 15 | 17 |
| Total candidate instances | 697 | ~12,700 |
| Backends verified per triple | 3 | 3 or 4 (SQL added where applicable) |
| New templates | — | decision-then, safety-confirm-delete |

Each triple carries: intent, ASG JSON, shell code, Python code, SQL code, expected output, node-type tags, backends verified list.

## What's next

- **Model distillation** — train specialist translators from verified data
- **The planner/composer** — reasoning agent over the translation organs
