# MK — Natural Language → Operating System

A layered translator that turns plain-English intents into real OS operations.
The same NL input compiles to **4 different backend targets** through a single
target-independent intermediate representation (ASG).

```
Human types NL → Planner (decompose) → ASG (parse) → Backend (compile/execute)
                                              ├─ direct  (immediate execution)
                                              ├─ shell   (/bin/sh script)
                                              ├─ python  (standalone .py)
                                              └─ sql     (SQLite script)
```

## Quick Start

```bash
# One-shot: type NL, get results
python3 mk.py 'create file hello.txt with content "world"'
python3 mk.py 'read file hello.txt'

# Compound shortcuts — deterministic, no model needed
python3 mk.py 'backup data.txt'
python3 mk.py 'inspect config.txt'
python3 mk.py 'init project myapp'

# Multi-backend: same intent, different target language
python3 mk.py --backend shell 'count lines in data.txt'
python3 mk.py --backend python 'count lines in data.txt'
python3 mk.py --backend sql 'count lines in data.txt'
python3 mk.py --show-all 'count lines in data.txt'

# REPL mode
python3 mk.py
mk> :help
mk> backup log.txt
mk> :backend shell
mk[shell]> count lines in log.txt
mk> :quit
```

## Architecture

| Layer | File | Role |
|-------|------|------|
| **Planner** | `planner.py` | Decomposes complex NL into ASG-parseable steps (37 deterministic rules + LLM fallback) |
| **ASG** | `asg.py` | 16-node target-independent intermediate representation |
| **Direct** | `interpreter.py` | Executes ASG nodes immediately |
| **Shell** | `terminal_backend.py` | Compiles ASG → /bin/sh script |
| **Python** | `python_backend.py` | Compiles ASG → standalone Python source |
| **SQL** | `sql_backend.py` | Compiles ASG → SQLite SQL script |
| **CLI** | `mk.py` | Unified front-door (one-shot + REPL) |
| **Council** | `council.py` + `run.py` | Overnight language-design by anonymous Borda consensus |

## Compound Shortcuts

37 deterministic rules that decompose common multi-step patterns — no model needed:

| Shortcut | Decomposes To |
|----------|--------------|
| `backup NAME` | `copy NAME to backup_NAME` |
| `inspect NAME` | `read + count lines + count words` |
| `summarize NAME` | `read + lines + words + sum numbers` |
| `init project NAME` | `mkdir + create README` |
| `ensure NAME exists` | conditional: read if exists, else create |
| `touch NAME` | conditional: count if exists, else create |
| `upsert NAME with "TEXT"` | conditional: append if exists, else create |
| `rename OLD to NEW` | `copy + delete confirm` |
| `grep "TEXT" in NAME` | `extract lines matching` |
| `wc NAME` | `count lines + count words` |
| ... | (+ 26 more) |

Also auto-splits conjunctions: `X then Y`, `X; Y`, `X → Y`.

## ASG Node Types (16)

`CreateFile`, `ReadFile`, `AppendFile`, `CountLines`, `CountWords`, `SortLines`,
`HeadLines`, `SumNumbers`, `ExtractPattern`, `CopyFile`, `MakeDirectory`,
`MoveFile`, `ListFiles`, `FindFiles`, `DeleteFile`, `Conditional`.

## Safety Model (fail-CLOSED)

All irreversible operations refuse unless explicitly confirmed:
- Create refuses overwrite · Append refuses missing file · Delete requires confirm
- Copy/Move refuse if destination exists

## Test Suite

```bash
python3 test_v03.py       # 89 rungs — ASG, 4 backends, cross-target invariants
python3 test_planner.py   # 91 rungs — planner decomposition + CLI + multi-backend
python3 _verify_all.py    # 11 rungs — v02 backward compatibility
                         # Total: 191 rungs, all green
```

## Data Pipeline

`generate_triples.py` produces ~12.7K verified NL→intent→output triples across
40 filenames, 45 content variants, 24 number sets, and 17 templates — verified
through all 4 backends.

## License

MIT
