# kinox — session report (2026-06-23): launcher TUI + token-ingestion stack

## TL;DR
- Shipped the **launcher hub** — the default working environment. Bare `kx`/`kin`
  open a menu; pick a scope → it launches Claude Code there → you return to the
  menu when it exits.
- Wired a **two-layer token-ingestion stack** into Claude Code (global hooks):
  **groom** (augments your prompt) + **RTK / Rust Token Killer** (compresses
  command output 60–90%).
- `main` is green: **249 tests pass**, ruff + pyright clean (now incl. `kx`),
  kernel purity intact. Not pushed to origin.

---

## What we did this session

### 1. Launcher TUI — the default working environment (4 TDD goals, merged)
New product `products/launcher/`. Rule-Zero reuse: `questionary` (selection) +
`rich` (header); no fzf/gum/Textual/hand-rolled curses.
- **G4-1** `06024d1` — `menu.py build_menu()`: admin + sorted projects + action
  rows as pure data (`MenuItem`). 7 tests.
- **G4-2** `2cb8bf8` — `app.py run()`: hub loop, routes the choice, loops until
  quit; all terminal I/O injected. No-TTY → prints the plan, exits 0. 8 tests.
- **G4-3** `4b0cc03` — real seams: `default_select` (questionary, separator
  before the actions) + numbered `text_select` SOFT fallback; `default_render`
  (rich). Added `questionary` to the `tui` extra + dev group.
- **G4-4** `357e239` — wired the seam: bare `kx`/`kin` → hub; `make_kin_spawner`
  spawns `kin claude` (subprocess, so control returns); direct shortcuts
  unchanged; `_ensure_venv` re-exec so deps import on the cold `~/.local/bin`
  path.

### 2. Hardening
- `925b04d` — **gated `kx`** (added to ruff `extend-include` + pyright
  `include`; it was extensionless → skipped, and that hid a redundant-import
  defect, now fixed). Refreshed the stale `kx` docstring.
- Pruned 19 stale merged branches. `m1-broker` left intact (21 UNMERGED commits
  of exploratory research/docs — **your call**: keep / archive / cherry-pick).

### 3. Token-ingestion stack (two complementary layers, both global hooks)
| Layer | Hook | Direction | Effect |
|---|---|---|---|
| **groom + `broker_tag`** | `UserPromptSubmit` | prompt **in** | augments — redact → expand → context → tag (local-LLM tag offload, SOFT keyword fallback) |
| **RTK (Rust Token Killer)** | `PreToolUse: Bash` | tool output **in** | compresses `git`/`test`/`ls`/`grep`/… output 60–90% |

- Groom hook command:
  `PYTHONPATH=/home/khalid/kinox /home/khalid/kinox/.venv/bin/python -m adapters.claude_code`
- RTK: `rtk-ai/rtk` v0.42.4 (already installed), wired via `rtk init -g`
  (`rtk hook claude`). Config: `~/.config/rtk/filters.toml`. Instructions:
  `~/.claude/RTK.md` (+ `@RTK.md` in `~/.claude/CLAUDE.md`).
- Both verified coexisting in `~/.claude/settings.json`. **They take effect on
  the NEXT Claude session.** Backups: `~/.claude/settings.json.bak-*`.
- Disable: `rtk init -g --uninstall` (RTK) / empty the `UserPromptSubmit` array
  or restore a backup (groom).

### 3b. Hook logging (observability) — ACTIVE
Both hooks are routed through transparent tee-loggers
(`tools/hooklog/{groom,rtk}-hook-logged.sh`) that dump raw stdin (input) + raw
stdout (output) per invocation, while passing stdout through unchanged and
preserving the exit code (verified identical to the raw commands).
- Dump files: `~/.kinox/hooklog/groom.log`, `~/.kinox/hooklog/rtk.log`.
- Watch live: `tail -f ~/.kinox/hooklog/groom.log ~/.kinox/hooklog/rtk.log`.
- Each record = timestamp + `--- INPUT ---` block + `--- OUTPUT ---` block.
  Example: groom logs your prompt JSON → emitted tags/context; rtk logs the Bash
  payload → its rewrite (`git status` → `rtk git status` via `updatedInput`).
- **Turn OFF** (revert to raw, no logging): point the two commands in
  `~/.claude/settings.json` back at
  `PYTHONPATH=/home/khalid/kinox /home/khalid/kinox/.venv/bin/python -m adapters.claude_code`
  and `rtk hook claude` — or restore `~/.claude/settings.json.bak-hooklog-*`.

### 4. Parked candidate models (evaluated, not adopted)
Read each card; **none are context compressors**:
- **BAAI/bge-reranker-v2-m3** — relevance reranker (0.6B, Apache-2.0).
  **PARKED** for a future *context-selection* stage (retrieve → rerank → top-k).
- **livekit/turn-detector** — voice end-of-utterance detection. **Rejected**
  (wrong domain, proprietary license).
- **sakmkmk2/Vibe-Coding-Claude-Fable-5** — generic Qwen2.5-7B coding finetune,
  misleading name, sketchy card. **Rejected** for compression.

---

## How to enter the framework — line for line

> One-time setup is already done on this machine (symlinks in `~/.local/bin`,
> `uv sync` run, Ollama up). Skip to **Enter** unless something's broken.

### One-time setup (only if `kx` is missing)
```bash
cd ~/kinox
./install.sh          # uv sync + symlink kx, kin into ~/.local/bin
which kx kin          # expect: /home/khalid/.local/bin/kx and /kin
```
If `which` finds nothing, ensure `~/.local/bin` is on your `PATH`, then re-open
the shell.

### Enter (from any directory)
```bash
kx                    # opens the launcher HUB — arrow-key pick a scope/action
```
Other entries:
```bash
kx kin                # skip the hub → straight into the admin scope (repo root)
kx <project>          # skip the hub → into an existing project
kx new <project>      # scaffold projects/<project>/ then enter it
kin                   # same as bare kx (opens the hub)
kin claude            # admin scope, straight to Claude (bypass hub)
kin shell             # admin bash subshell (no Claude)
```
If you get `command not found` right after install:
```bash
hash -r               # clear the shell's stale command cache, then retry
```

### What happens when you enter
1. The chosen entry launches `claude --dangerously-skip-permissions` in that
   scope's directory (venv active).
2. **Both ingestion hooks are now live** (they load at session start):
   - every prompt you submit → groomed (tags + git context added);
   - every Bash command Claude runs → output compressed by RTK.

### Verify the stack is working (inside the new session)
```bash
git status            # RTK compresses this; you may see a [rtk] marker
rtk gain              # shows cumulative token savings
ollama list           # confirm a model is up for the LLM tag offload
                      # (if Ollama is down, groom SOFT-falls-back to keyword tags)
```

---

## Pick up here next session (priority order)
1. **Light up the dashboard** — `kx status` reads `~/.kinox/broker-events.jsonl`
   but groom/hook write `~/.kinox/events.jsonl` (TWO logs). Reconcile, then run
   the pipeline once for real rows. (Also lights up the hub's *dashboard* action.)
2. **Decide `m1-broker`'s fate** (21 unmerged research commits).
3. **(Optional) context-selection stage** using the parked `bge-reranker-v2-m3`
   — design first (retrieve candidate files/snippets → rerank → feed top-k).
4. **(Optional) prompt-body compression** via LLMLingua-2 (RTK already covers
   command output, the bigger sink).
5. **(Optional) push `main`** to origin; gate `kin` with shellcheck.

## Discipline (binding)
kernel/ stdlib-only (imports nothing outward); daemon→kernel OK, products→daemon
OK. uv tooling; green gates = pytest + ruff + pyright + kernel purity before any
"done". Rule Zero (reuse before build). Invoke `project-alignment` before coding.
`RALPH_GOALS_*` + `.claude/ralph-loop.local.md` are gitignored (never committed).
