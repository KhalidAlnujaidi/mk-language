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
   │  execute in sandbox / in-memory SQLite
   ▼
verified OS outcome
```

Add a new target = add one backend. No change to the parser or existing backends.

## Architecture

| File | Role |
|------|------|
| `asg.py` | ASG node dataclasses (16 types) + NL parser (`parse(source) → [nodes]`) |
| `interpreter.py` | Direct executor (`run(source)` → OS effects, backward-compat with v02 sandbox) |
| `terminal_backend.py` | Shell code generator (`compile_to_shell(nodes) → str`) |
| `python_backend.py` | Python code generator (`compile_to_python(nodes) → str`) |
| `sql_backend.py` | SQL code generator + SQLite executor (`compile_to_sql(nodes) → str`, `execute_sql(nodes) → str`) |
| `council.py` | Council loop + scored conformance (`_score_capability`, `score_interpreter`, `run_build_round`) |
| `run.py` | Main driver — gradient-aware plateau detection, fractional score feedback to models |
| `test_v03.py` | Full test suite: ASG, terminal, python, SQL, cross-target, scored conformance (89 rungs) |
| `_verify_all.py` | Original v02 11-rung conformance suite (unchanged, still 11/11) |
| `interpreter.v02.py` | Archived v02 interpreter (flat, no ASG) |

## Test results (89 rungs)

```
Phase A:  ASG Parse → Execute           11/11  (100%)  ✅
Phase A+: ASG Structure Validation        7/7   (100%)  ✅
Phase B:  Terminal Backend (ASG→Shell)   13/13  (100%)  ✅
Phase B+: Terminal-Native Compute          5/5   (100%)  ✅
Phase C:  Python Backend (ASG→Python)    11/11  (100%)  ✅
Phase C+: Python-Native Compute            5/5   (100%)  ✅
Phase D:  Cross-Target Invariant         11/11  (100%)  ✅  (direct vs shell vs python)
Phase D+: Cross-Target Compute Invariant   5/5   (100%)  ✅
Phase E:  SQL Backend (ASG→SQL→SQLite)   11/11  (100%)  ✅  (same 11 conformance programs)
Phase E+: SQL-Native Compute               5/5   (100%)  ✅  (count-words, sort, head, sum, extract)
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

## SQL backend design (sql_backend.py)

The SQL backend proves the ASG extends to a non-OS target. Key design decisions:

- **File → Table mapping**: filenames preserved using SQLite double-quoted identifiers. `"notes.txt"` stays `"notes.txt"` — full cross-target naming consistency.
- **Line-oriented model**: each file is a table with a single `line TEXT` column; each line of the file is a row. This preserves the interpreter's line-oriented semantics.
- **Two-tier API**: `compile_to_sql(nodes)` generates readable SQL (for inspection); `execute_sql(nodes)` runs against in-memory SQLite and returns stdout (for conformance testing).
- **Semantic gaps handled**: `SumNumbers` and `FindFiles` use Python-side processing in the executor (SQLite lacks regex extraction and dynamic table queries).
- **Safety model**: fail-CLOSED — `DeleteFile` without confirm returns `REFUSED`, `CreateFile` guards against existing tables, etc. Matches interpreter and other backends exactly.

## Key engineering decisions

### ASG design (asg.py)
- 16 frozen dataclasses, each with `node_type ∈ {Process, Terminal, Decision}`
- Decision nodes carry sub-graphs (`then_branch`, `else_branch` as node lists)
- `parse_line()` uses ordered regex matching — `delete X confirm` checked before `delete X`

### Terminal backend (terminal_backend.py)
- `count_lines`: uses `awk 'END{print NR}'` not `wc -l` (the bug that caused v02's 119-round plateau)
- All user input `shlex.quote`'d — injection-proof by construction

### Scored conformance (council.py + run.py)
- **5-tier scoring**: 1.0 (exact), 0.5 (near-miss), 0.3 (crash), 0.1 (empty/timeout), 0.0 (no code)
- `run_build_round` adopts proposals on gradient improvement, not just integer capability gains
- `run.py` plateau detection resets `stall_count` on gradient gains
- Models see fractional scores + reason strings in their build prompts

## Verified data pipeline

`generate_triples.py` produces 697 verified triples across 15 templates × 3 backends:
- Exported as `triples.jsonl` (1.1 MB), 100% verification rate

## What's next

- **Scale the data pipeline** — expand parameter pools to reach 5K–10K triples for distillation
- **Model distillation** — train specialist translators from verified data
- **The planner/composer** — reasoning agent over the translation organs
