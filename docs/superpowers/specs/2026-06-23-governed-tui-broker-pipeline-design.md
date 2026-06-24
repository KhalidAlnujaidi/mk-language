# Governed TUI front-end + active broker pipeline

**Date:** 2026-06-23
**Status:** approved (brainstorming → implementation)
**Branch base:** `main` → feature branch `feat-governed-tui-pipeline`
**Supersedes (partially):** `2026-06-23-launcher-tui-design.md` §"The seam" —
that doc deliberately let the direct shortcuts (`kx kin`, `kx <project>`,
`kx new`) `execve` straight into claude with **no return**. This design reverses
that: every entry point stays encapsulated within the TUI.

## Purpose

Make the launcher TUI the single governed front-end for kinox. Every entry into
the framework whose command begins with `kx` lands in the **hub TUI**; what you
type there flows through the **local pipeline** — hooks → groom (the fuzzy
`tag` step routed to a local model) → **broker daemon** — into a **fresh, clean
Claude Code subprocess**, and when that session exits you return to the hub. The
broker daemon — the backbone — is brought up automatically and is actually used
by the pipeline (today it is built but idle).

Three coupled pieces, built as one design:

1. **Broker activation** — make the daemon live and actually on the groom path.
2. **Vendor the pipeline into the repo** — the framework runs its own hooks.
3. **Unify the TUI front-end** — one path in, spawn-and-return, role-gated output.

## Rule Zero (search-and-reuse)

`~/kinox` is out of scope for the alignment model-table/SILMA/GPU rules (those
bind the two Desktop projects only), but Rule Zero applies machine-wide. This
design is **composition of already-built parts**, not new construction:

- **Reuse — broker:** `daemon/` is M1 "broker brick 1", code-complete and fully
  tested (`server.py` FastAPI + Unix-socket entrypoint; `registry`, `resources`,
  `scoring`, kernel `router`, `fallback`, `backends` (Ollama), `exec`,
  `guardian`, `watchdog`, `outbox`, `serializer`, `doctor`). We add no broker
  logic — only an "ensure it is running" launch path and the groom→broker wire.
- **Reuse — TUI:** `products/launcher/` (questionary + rich), already the product
  of the prior Rule-Zero pass. We reuse `make_kin_spawner` (spawn-and-return) and
  the `run()` hub loop; we only remove the competing `execve` path.
- **Reuse — serving/supervision:** `uvicorn` (already a dep) for the socket;
  no new process manager. Autostart is **lazy `kx`-ensures-up** (chosen over
  `systemd --user` and the in-repo watchdog) — no new host-install step, fully
  in-repo and unit-testable.
- **Searched, nothing new needed:** no external supervisor / launcher / hook
  framework is pulled in; every required piece already exists in the repo.

## Architecture & layering

No new top-level package. Changes land in existing layers:

- `kx` (entrypoint) — routing change: all `kx*` → the hub; broker ensure-up.
- `products/launcher/app.py` — role-gated output; the hub stays the container.
- `products/groom/` — the `tag` step calls the broker instead of resolving to a
  deterministic tier.
- `daemon/` — unchanged logic; a thin module-level helper to check/start the
  socket (or this lives in `products/`, keeping `daemon/` import-clean).
- `.claude/settings.json` (new, repo-local) — registers the framework hooks.

`kernel/` stays stdlib-only and imports nothing outward (`test_architecture.py`
stays green). The broker-ensure-up helper lives in the outer layer
(`products/` or `daemon/`), never in `kernel/`.

## Piece 1 — Broker activation (backbone)

**Ensure-up (lazy).** Before launching any session, `kx` checks the broker
socket (`KINOX_BROKER_SOCKET`, default `/run/kinox/broker.sock`). If it is absent
or not accepting connections, `kx` starts `uvicorn daemon.server:app --uds
<sock>` **detached**, polls readiness with a bounded timeout, and logs to
`~/.kinox/`. If already healthy → no-op.

**Explicit control.** New `kx broker {status|start|stop}`. `kx doctor` reports
broker health (socket present + a `/broker/status` probe).

**Wire the groom `tag` step through the broker.** Today `~/.kinox/events.jsonl`
shows the fuzzy `tag` step logging `tier: "deterministic"` — the model leg is
dormant. Route `tag` through the broker so a successful call logs
`tier: "model:<where>"`. The model is chosen by the broker's router (vision
§5.4: FUZZY → small local model, capped tokens), not hard-coded here.

**Fail-soft.** Broker down and cannot start → `tag` falls back to the current
deterministic behavior; the degradation is surfaced in the TUI for admin/dev
roles only. The framework never blocks on the broker.

## Piece 2 — Vendor the pipeline into the repo

Add a **repo-local `.claude/settings.json`** registering:

- the groom `UserPromptSubmit` hook (`adapters/claude_code.py`), and
- the **dev-guard** hook (`adapters/guard.py`).

Because each `kx` session `cd`s into the repo (or a project under it) and
launches claude there, claude picks up the repo-local settings — so every `kx`
session runs the **framework's own** pipeline, independent of the user's global
`~/.claude/settings.json`. The global hooks remain as a harmless fallback (if
present, they are redundant; if absent, the repo still works). Secrets/paths in
the settings stay relative to the repo so the file is portable and committable.

## Piece 3 — Unify the TUI front-end

**One path in.** All `kx*` entries route to the hub: bare `kx`, `kx kin`,
`kx <project>`, `kx new <p>`. The `execve` bypass in `kx:140-154` (`_enter`) is
removed.

**Spawn-and-return, fresh every time.** Named scopes keep their fast path: `kx
kin` / `kx <proj>` **pre-select** that scope and spawn it immediately via the
existing `make_kin_spawner` (a fresh Claude Code subprocess, clean context),
then fall into the normal hub loop on exit — so you always come back to the TUI.
`kx new` scaffolds, then enters the new project the same way. No `execve`
anywhere; the hub is the persistent container.

**Role-gated output.** The `kin` banner (`root` / `scope` / `plan`) and the
broker ensure-up lines print **only for `admin` or `developer`** roles; other
sessions get a quiet TUI. Roles already exist via `select_role` / `KINOX_ROLE`.
(Assumption, resolved: there is no third "silent" role today — "printed only for
admin/dev" means verbose for those two roles, minimal otherwise.)

## Data flow (one session)

```
kx [scope] ─▶ ensure broker up (lazy) ─▶ hub TUI (role-gated banner)
                                              │  user picks / pre-selected scope
                                              ▼
                         spawn kin claude (fresh subprocess, KIN_SCOPE_DIR set)
                                              │  claude session runs under
                                              │  repo-local hooks:
                                              │    UserPromptSubmit → groom
                                              │      redact→expand→context→tag
                                              │      tag ──HTTP/uds──▶ broker ──▶ Ollama
                                              ▼
                              session exits ─▶ back to hub TUI (bell, redraw)
```

## Error handling & TTY-gating

- **No TTY** (tests/pipes/CI) → print the plan and `exit 0`; never start the
  broker, never enter the interactive loop (existing contract preserved).
- **questionary import fails** → numbered text-menu fallback (existing).
- **broker unreachable** → fail-soft deterministic `tag`; surfaced to admin/dev.
- **claude missing** → existing `kin` fallback to the admin shell (unchanged),
  reachable via `kin shell` as an explicit escape hatch.

## Testing (TDD)

- **Broker ensure-up:** inject a fake starter + socket probe — healthy→no-op,
  absent→start once, dead→restart; bounded readiness poll; `kx broker status`
  output. No real uvicorn in unit tests.
- **groom `tag` → broker:** fake broker client returns a routed tier; assert the
  emitted `EventRecord.tier == "model:<where>"`; broker-down path asserts the
  deterministic fallback tier.
- **Repo hooks:** assert `.claude/settings.json` registers the groom +
  dev-guard hooks and is valid JSON against the hook schema.
- **TUI unification:** extend `tests/test_launcher_app.py` — `kx kin` /
  `kx <proj>` route through spawn-and-return (record the spawn, assert **no**
  execve) and land back in the hub until `quit`; role-gating of the banner;
  non-TTY prints the plan and exits 0.
- **Gates:** `pytest -q`, `ruff check .`, `pyright`, and `test_architecture.py`
  (kernel purity) all green on `feat-governed-tui-pipeline`; merged `--no-ff`.

## Out of scope (YAGNI)

- Per-prompt fresh subprocess (explicitly rejected — sessions are fresh, prompts
  within a session are not).
- Textual full-screen / live-refreshing panels; mouse; multi-select.
- Voice input, the business plane, self-evolving proposals.
- `systemd --user` / standalone watchdog supervision (lazy ensure-up chosen).
```
