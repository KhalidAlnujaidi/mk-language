# Launcher TUI — the default working environment

**Date:** 2026-06-23
**Status:** approved (brainstorming → implementation)
**Branch base:** `main`

## Purpose

Make a **hub menu-loop** the default working environment for kinox. Any entry
into the framework without a named scope lands on a home screen that lists the
admin scope + every project + a few actions; you pick one, it runs, and when it
exits you return to the hub. Things like the dashboard live *inside* the hub
rather than being separate commands you have to remember.

This is the long-deferred "custom TUI at the `_enter`/`kin` seam." It sits
*before* the claude launch: the hub picks a scope, then hands off to the
existing `kin` launcher.

## Rule Zero (search-and-reuse)

Searched: `fzf` / `gum` (system binaries, not installed, not uv-pinnable, split
logic into bash, hard to unit-test) vs Python menu libs. **Chosen reuse:**
`questionary` (maintained, `prompt_toolkit`-based, native `Separator`/`Choice`
— renders a sectioned list with a cursor exactly like the mockup) for
selection, and the already-present `rich` for the header. No hand-rolled
`curses`. Lighter alternative considered and rejected for now: `simple-term-menu`
(no native separators).

## Architecture & layering

New outer-layer product `products/launcher/`, split for testability:

- **`menu.py` — pure, no I/O.** `build_menu(projects_dir, *, manifest=None) ->
  list[MenuItem]`. `MenuItem = (key, label, kind, scope_dir)`,
  `kind ∈ {admin, project, new, dashboard, doctor, quit}`. Data only — fully
  unit-testable.
- **`app.py` — the interactive loop.** Renders the header (`rich`), presents the
  menu (`questionary`), dispatches the choice. Injectable seams (`select=`,
  `spawn=`, `is_tty=`) so the loop is testable without a real terminal.

`launcher` may import `kernel` (manifest/doctor) and reuse `daemon`; it imports
nothing into `kernel`. `tests/test_architecture.py` stays green.

## The seam — spawn, don't exec

Today every entry `execve`s `kin` → `exec claude` (process replaced, no return).
The hub instead **spawns `kin` as a subprocess** with `KIN_SCOPE_DIR` set, waits,
then loops back to the menu. `kin` is reused unchanged: as a child its
`exec claude` replaces only the child; when claude exits, control returns to the
hub. No env-setup duplication.

- Bare **`kx`** → the hub loop.
- Bare **`kin`** → delegates to the hub (`exec kx`), so "run it from anywhere"
  lands in the home base. **`kin claude`** / **`kin shell`** stay as direct
  bypasses.
- Direct shortcuts keep current behavior (no return — you named a scope):
  **`kx kin`**, **`kx <project>`**, **`kx new <p>`** still `_enter`/execve
  straight into claude.

From the hub: *scope* → spawn claude there → back; *dashboard* → render `kx
status` inline → back; *doctor* → run → back; *new project* → prompt name,
scaffold, enter it; *quit* → exit.

## Error handling & TTY-gating (the discipline)

- **No TTY** (tests/pipes/CI) → print the menu as a plan and `exit 0`, never
  enter the interactive loop (same contract as `kin`). `questionary` needs a TTY,
  so this guard is load-bearing.
- `questionary` import fails → SOFT fall back to a numbered text menu via
  `input()`.
- `claude` missing → `kin` already drops to the admin shell. Unchanged.

## Testing

- `menu.py`: pure — admin first, N projects listed, action rows present, empty
  `projects/` handled.
- `app.py`: inject fake `select` (returns a chosen key) + fake `spawn` (records
  the call) → assert dispatch routes correctly and the loop returns to the menu
  until `quit`; plus a non-TTY test (prints plan, exits 0, no hang).
- Green gates: pytest + ruff + pyright + kernel purity, on `feat-launcher-tui`,
  merged `--no-ff`.

## Out of scope (YAGNI)

Full-screen panelled live app (Textual), live-refreshing status panes, mouse
support, multi-select. The hub is a menu-loop, not a dashboard framework.
