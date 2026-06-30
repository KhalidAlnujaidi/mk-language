# Governance Enforcement & Standardization

_A record of the governance and standardization work on kinox: what was changed,
why, how it is enforced, and what it guarantees. Written 2026-06-27 on branch
`feat-governed-tui-pipeline`._

---

## 1. Why this work happened

kinox runs coding agents. The moment more than one agent (or person) works at the
same time, the dominant failure mode stops being "too slow" and becomes **silent
overlap** — two writers touching the same file, one quietly winning, work lost
with no error. Three things were missing or leaking:

1. **No enforced non-overlap for parallel agents.** Multi-agent work was a
   convention (a file-ownership ledger), not a guarantee.
2. **Scope leakage.** A session opened *inside a project* could see the
   **framework's** internals and git state. Observed live: a project-scoped
   session reported the kinox repo's branch, commits, and `/par` history — because
   the project was a gitignored subdirectory of the framework repo, so `git`
   resolved upward, and the full framework preamble was injected into every
   session regardless of scope.
3. **No recoverable baseline.** A large pile of uncommitted/untracked work meant a
   slice could be detected-as-overlapping but never *rolled back*, and the green
   test suite secretly depended on untracked files a routine cleanup would delete.

The governing principle the work converged on: **there are exactly two scopes —
framework and project — and a project is told only its axioms, never the framework
that runs it.** Enforcement must be mechanical, not trusted.

---

## 2. The two-scope model

| | **Framework scope** | **Project scope** |
|---|---|---|
| Working *on* | kinox itself | a user project (`projects/<name>`) |
| Root / jail | repo root | the project directory |
| Injected context | axioms **+** framework internals | **axioms only** |
| Git repo | the kinox repo | its **own** isolated repo |
| Knows about the framework? | yes | **no** — only its axioms |

The scope is decided by one rule: **the repo root is the only framework scope;
everything else is a project** (`_is_framework_scope` in `products/chat/app.py`).

---

## 3. What was built, and why

### 3.1 Parallel fan-out with enforced non-overlap — the coordinator
**Files:** `products/agent/coordinator.py`, `tests/test_agent_coordinator.py`
**Commits:** `9299690`, `e5159b9`

A job can fan out to N agents, each owning a **disjoint slice** of paths:

- `assert_disjoint(...)` proves the owned sets don't overlap **before a single
  agent spawns** (fail-CLOSED). A contested partition is refused, not half-run.
- `ownership_guard(...)` confines each agent: it may write **only** inside its own
  slice; a write — direct or via the shell — into another agent's slice is
  refused. Reads may overlap freely (observing a file cannot override it).
- `run_parallel(...)` composes the root jail with the per-slice ownership guard and
  runs the agents concurrently (`asyncio.gather`).

**Why:** this is the constitution's *parallelism axiom* made executable — "there is
nothing to collapse and nothing to override." A conflict surfaces as a refused
action in the trace, never a lost edit.

Surfaced in the TUI as `/par` (project scope) and `/parf` (framework scope):
`task @ path1,path2 ;; task2 @ path3`.

### 3.2 Scope-aware preamble — a project sees only its axioms
**Files:** `alignment/AXIOMS.md` (new), `alignment/PREAMBLE.md` (trimmed),
`products/agent/environment.py`, `products/chat/app.py`
**Commits:** `f414755`, `fa30b3e`, `5a3a3fd`

The single injected preamble was split so each fact lives in exactly one file:

- **`alignment/AXIOMS.md`** — the universal governing rules (Rule Zero, the three
  theses, the parallelism axiom, honesty rails, working discipline). Injected into
  **every** scope.
- **`alignment/PREAMBLE.md`** — framework internals (architecture map, file
  layout, kernel rule, build conventions). Injected **only** in framework scope.

`environment.session_preamble(root, framework=...)` is the switch:
`build_axioms` (project) vs `build_preamble` = axioms + internals (framework).

**Why:** a project agent must follow the rules but must not be able to see the
framework's architecture, file paths, or self-structure. This closes the
knowledge half of the scope leak. Verified: the project preamble contains
`Rule Zero` but not the architecture map; the framework preamble contains both.

### 3.3 Every project is its own isolated repo
**Files:** `products/cli/commands.py`, `tests/test_cli_commands.py`,
`tests/test_kx.py`
**Commits:** `6d953fe`, `30b1618`, `ae6db44`, `3a0946e`

`scaffold_project` now runs `init_project_repo`: each project gets its own `.git`,
a project-scoped `.gitignore` (agent scratch and regenerable caches excluded), a
baseline commit, and is standardized onto the `main` branch — fail-soft if git is
absent.

- Existing projects backfilled: `c-computing`, `hdc`, `language` are each their own
  repo on `main`.
- `language` was special — it had been *tracked inside* the kinox repo. It was
  untracked (`git rm --cached`, files kept on disk, history preserved in the
  framework log) and re-initialized as its own repo.
- The framework repo now tracks **nothing** under `projects/` except
  `projects/.gitkeep`.

**Why:** every project needs a recoverable baseline that is *separate* from the
framework, so a project's work can be rolled back independently and never collides
with framework history. This closes the git half of the scope leak.

### 3.4 The bidirectional scope wall
**Files:** `products/agent/tools.py`, `products/chat/app.py`,
`tests/test_agent_tools.py`
**Commit:** `9901552`

The jail was one-directional: a **project** session was confined and could not
reach up into the framework, but a **framework** session (jailed to the repo root,
which *contains* `projects/`) could write **down** into a project — an overlap risk
when framework and project work run at the same time.

`project_root_guard` gained `deny_write_subpaths`. In framework scope the chat app
passes `("projects",)`, so a framework session may **read** a project but not
`write_file` or `run_bash`-mutate into it (fail-CLOSED). Reads still overlap
freely.

**Why:** to make the wall symmetric. Neither scope's *writes* cross into the
other, which is precisely what makes framework-and-project development safe to run
in parallel.

### 3.5 Codifying it in the immutable core
**File:** `alignment/CONSTITUTION.md`
**Commits:** `fa30b3e`, `21b1ac2`, `9901552`

The CONSTITUTION (the immutable core — "every design decision must trace back to a
thesis here") gained two axioms:

- **The parallelism axiom** — parallel agents own disjoint slices; nothing to
  collapse or override.
- **The scope axiom** — two scopes; a project is told only its axioms; the wall is
  enforced four ways (scope-aware preamble, root jail, bidirectional write wall,
  per-project isolation).

**Why:** governance that lives only in code is drift waiting to happen. Tracing it
from the immutable core makes it a rule, not an implementation detail.

### 3.6 Clean baseline & hygiene
**Commits:** `ff00f16`, `0d35444`, and the grouped commits that brought the tree
to zero uncommitted entries.

`.gitignore` now excludes `*.bak`, `/var`, `developer logs/`, and timestamped
session captures; the large in-flight surface was committed in logical groups; CI
gained a pyright ratchet on the pristine core.

**Why:** parallel slices are only recoverable if there is a clean committed
baseline to recover *to*.

---

## 4. What this guarantees

| Parallel combination | Safe | Mechanism |
|---|---|---|
| Project A ↔ Project B | ✅ | separate directories **and** separate git repos; each jailed to itself |
| Framework ↔ a Project | ✅ | project can't reach up (root jail); framework can read but **can't write down** (scope wall) |
| Many agents *within* framework (`/parf`) | ✅ | `assert_disjoint` + `ownership_guard`, fail-CLOSED |
| Many agents *within* a project (`/par`) | ✅ | `assert_disjoint` + `ownership_guard`, fail-CLOSED |

### The one boundary to respect
The **coordinator** (`run_parallel`) enforces non-overlap *within a single `/par`
or `/parf` fan-out*. Across **independent concurrent sessions**, the protection is
the **scope wall**, not the coordinator. So:

- Framework session **+** project session(s) at once → safe (the wall).
- Two different project sessions at once → safe (separate repos/dirs).
- For multiple agents in the **same** scope, drive them through **one** `/par` /
  `/parf` with disjoint slices — do **not** launch two *independent* same-scope
  sessions on the same files, since two uncoordinated same-scope sessions are not
  slice-checked against each other.

---

## 5. Mechanism reference

| Concern | Where |
|---|---|
| Parallel fan-out, non-overlap | `products/agent/coordinator.py` — `assert_disjoint`, `ownership_guard`, `run_parallel` |
| Scope-aware preamble | `products/agent/environment.py` — `build_axioms`, `build_preamble`, `session_preamble` |
| Scope detection | `products/chat/app.py` — `_is_framework_scope`, `_session_preamble` |
| Root jail + bidirectional wall | `products/agent/tools.py` — `project_root_guard(..., deny_write_subpaths=...)` |
| Per-project repo | `products/cli/commands.py` — `init_project_repo`, `scaffold_project` |
| The axioms (every scope) | `alignment/AXIOMS.md` |
| Framework internals (framework scope only) | `alignment/PREAMBLE.md` |
| The immutable rules | `alignment/CONSTITUTION.md` — parallelism axiom, scope axiom |

---

## 6. Verification

- Full suite: **467 passed**, ruff clean repo-wide, architecture guardrail green.
- Scope preamble: framework = axioms + internals; project = axioms only (no
  architecture map, no framework file paths).
- Wall, both directions: project→framework writes/bash blocked; framework→project
  writes/bash blocked, reads allowed.
- Baselines: framework repo clean; `c-computing`, `hdc`, `language` each clean and
  on `main`; new projects auto-init on `main`.

---

## 7. Commit trail (this work)

```
9901552  feat(agent): bidirectional scope wall — framework may not write into projects
21b1ac2  docs(alignment): codify the scope axiom in the immutable core
3a0946e  chore(cli): standardize new project repos on the main branch
ae6db44  chore(cli): exclude regenerable caches from new-project .gitignore
30b1618  chore: untrack projects/language — projects are isolated repos
6d953fe  feat(cli): every new project is its own isolated git repo
5a3a3fd  feat(agent): scope-aware preamble — a project sees only its axioms
fa30b3e  docs(alignment): preach the parallelism axiom in the injected preamble
f414755  feat(agent): single-source preamble (PREAMBLE.md) + multi-turn history
0d35444  chore(ci): pyright ratchet on the pristine core + ruff scope
ff00f16  chore(gitignore): ignore *.bak, /var, developer logs, session captures
e5159b9  feat(tui): /par and /parf — parallel disjoint-slice agents
9299690  feat(agent): parallelism axiom — fan out to disjoint-slice agents, no override
```
