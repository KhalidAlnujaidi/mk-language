# The Council Language — capability ladder (executed, not voted)

**68/68 rungs pass** across 8 phases. Every rung is execution-verified in a sandbox.

## Phase A — ASG Parse → Execute (11 rungs)

The original v02 capabilities, now flowing through the ASG intermediate graph.

- ✅ **create-and-read** — create + read → expected content
- ✅ **list-dir** — create + list → expected filename
- ✅ **append** — create + append + read → concatenated content
- ✅ **count-lines** — create + append × 2 + count → line count
- ✅ **copy** — create + copy + read dest → source content
- ✅ **mkdir-move** — create + mkdir + move + list → moved file
- ✅ **search-content** — create × 2 + find → matching file
- ✅ **sequence** — create × 2 + list → both files
- ✅ **decision** — conditional (file missing → else-branch creates it)
- ✅ **safety-refuse-irreversible** — delete without confirm → REFUSED
- ✅ **safety-confirm-irreversible** — delete with confirm → file removed

## Phase A+ — ASG Structure Validation (7 rungs)

Verifies the parser produces correct node types and graph shapes.

- ✅ **parse-create-type** — `create file` → `CreateFile` node
- ✅ **parse-conditional-branches** — `if...then...otherwise` → `Conditional` with both branches
- ✅ **parse-sequence-length** — multi-line → correct node count
- ✅ **parse-count-words** — `count words in` → `CountWords` node
- ✅ **parse-head-lines** — `show first N lines of` → `HeadLines` node with count=N
- ✅ **parse-sum-numbers** — `sum numbers in` → `SumNumbers` node
- ✅ **parse-extract-pattern** — `extract lines matching "..." from` → `ExtractPattern` node

## Phase B — Terminal Backend (13 rungs)

ASG → shell script → execute in sandbox → same output as interpreter.

- ✅ All 11 original rungs through `compile_to_shell()`
- ✅ **grep-pipe** — find files containing text in a single file
- ✅ **multi-file-search** — find files containing text across multiple files

## Phase B+ — Terminal-Native Compute (5 rungs)

New computational intents compiled to shell commands.

- ✅ **count-words** — `count words in w.txt` → `4` (via `wc -w`)
- ✅ **sort-lines** — `sort lines in s.txt` → `apple banana cherry` (via `sort`)
- ✅ **head-lines** — `show first 2 lines of h.txt` → `first second` (via `head -n`)
- ✅ **sum-numbers** — `sum numbers in nums.txt` → `35` (via `grep -oE` + `awk`)
- ✅ **extract-pattern** — `extract lines matching "error" from log.txt` → matching lines (via `grep`)

## Phase C — Python Backend (11 rungs)

ASG → standalone Python source code → execute → same output.

- ✅ All 11 original rungs through `compile_to_python()`

## Phase C+ — Python-Native Compute (5 rungs)

Same computational intents compiled to independently-runnable Python code.

- ✅ **count-words** — `len(content.split())`
- ✅ **sort-lines** — `sorted(lines)`
- ✅ **head-lines** — `lines[:N]`
- ✅ **sum-numbers** — `sum(int(x) for x in re.findall(r'\d+', content))`
- ✅ **extract-pattern** — `[l for l in lines if pattern in l]`

## Phase D — Cross-Target Invariant (11 rungs)

The same intent compiled through all three targets (direct, shell, Python) produces
the **same verified OS outcome**. This proves the ASG is genuinely target-independent.

- ✅ All 11 original rungs: direct == shell == python == expected

## Phase D+ — Cross-Target Compute Invariant (5 rungs)

The new computational intents also produce identical output across all three targets.

- ✅ **count-words** — direct == shell == python == `4`
- ✅ **sort-lines** — direct == shell == python == `apple banana cherry`
- ✅ **head-lines** — direct == shell == python == `first second`
- ✅ **sum-numbers** — direct == shell == python == `35`
- ✅ **extract-pattern** — direct == shell == python == matching lines

---

## Scored conformance model

Every rung yields a **0–1 score** with a reason string, replacing boolean pass/fail.

Implemented in `_score_capability` (council.py) and wired through `score_interpreter` →
`run_build_round` → `run.py` main loop. The gradient is visible to models in their build
prompts, and plateau detection resets on gradient gains, not just integer capability gains.

| Score | Meaning |
|-------|---------|
| 1.0 | Exact match — expected output produced |
| 0.5 | Ran without error, produced output, but wrong (near-miss) |
| 0.3 | Program crashed (nonzero exit with traceback) |
| 0.1 | Produced empty output or timed out |
| 0.0 | No code / runner error |

This directly addresses the 119-round plateau root cause: boolean scoring hid near-misses
that a gradient would have revealed as progress.

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

## Backend inventory

| Backend | File | Output |
|---------|------|--------|
| Direct execution | `interpreter.py` | OS effects + stdout |
| Shell codegen | `terminal_backend.py` | Standalone `/bin/sh` script |
| Python codegen | `python_backend.py` | Standalone `.py` source |

## Safety model (fail-CLOSED)

| Operation | Without confirmation | With confirmation |
|-----------|---------------------|-------------------|
| DeleteFile | REFUSED | Executed |
| CreateFile (exists) | REFUSED | — (always guards) |
| AppendFile (missing) | REFUSED | — (always guards) |
| CopyFile (dest exists) | REFUSED | — (always guards) |
| MoveFile (dest exists) | REFUSED | — (always guards) |
| MakeDirectory (exists) | REFUSED | — (always guards) |
