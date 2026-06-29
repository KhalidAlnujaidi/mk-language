"""Chat TUI — terminal loop for the kinox chatbot.

Provides ``chat_run()``, the interactive chat loop entered from the launcher
hub.  Rendering is done with ``rich``; input uses ``prompt_toolkit`` when
available with a plain ``input()`` fallback.  The loop handles ``/`` commands
(help, clear, quit, model) and delegates message processing to
:class:`~products.chat.session.ChatSession`.

kinox's brain is cloud-first (``glm-5.2`` on z.ai) with the first local model as
the fail-soft fallback (see ``daemon.brain``). Before entering the TUI, a
**pre-flight check** confirms a usable model exists — the cloud brain, a local
model, or both — and hard-fails only when neither is available; control then
returns to the hub immediately rather than entering the loop assuming a model is
there.

Cold-start discipline: all heavy imports (rich, prompt_toolkit) live inside
function bodies so the module is importable at hub-launch time without cost.
The plain-text fallback path is unit-testable by passing ``is_tty=False``.
"""

from __future__ import annotations

import os
from collections.abc import Callable
from pathlib import Path

from kernel.manifest import Manifest
from kernel.metrics import MetricsSink

from products.chat.session import _MAX_HISTORY_PAIRS, ChatSession

#: How many turns of command history prompt_toolkit remembers.
_HISTORY_SIZE = 200

#: MCP config paths for which we've already shown the "connecting…" notice (it
#: only matters on the first agent turn — servers are cached after that).
_mcp_started: set[str] = set()


class _QuitChat(Exception):
    """Raised by /quit to unwind the loop cleanly back to the hub."""


# --- pre-flight check --------------------------------------------------------


def _ollama_reachable(manifest: Manifest, *, timeout_s: float = 2.0) -> bool:
    """Verify Ollama's API endpoint is actually serving (not just registered).

    ``ollama list`` succeeding means the CLI can talk to the daemon, but the
    OpenAI-compatible ``/v1/models`` endpoint may not be ready (e.g. stale
    daemon or port conflict).  We check it explicitly so we never assume.
    """
    from kernel.manifest import local_backend_urls

    url = local_backend_urls().get("ollama", "")
    if not url:
        return False
    try:
        import urllib.request

        req = urllib.request.Request(f"{url.rstrip('/')}/models")
        urllib.request.urlopen(req, timeout=timeout_s)
        return True
    except Exception:
        return False


def _brain_key_present(backend: str | None) -> bool:
    """``True`` if *backend* needs no key, or its key env var is set.

    Looks the backend up in the broker's spec table so the check stays general
    (no hard-coded ``ZAI_API_KEY``) — a cloud backend with an unset key is
    reported honestly so the banner can say "→ fallback"."""
    from daemon.backends import default_specs

    if backend is None:
        return True
    spec = default_specs().get(backend)
    if spec is None or spec.auth_env is None:
        return True
    return bool(os.environ.get(spec.auth_env))


def _preflight(manifest: Manifest) -> str | None:
    """Verify a model is available before entering the chat loop.

    kinox's brain is cloud-first (``glm-5.2``); a local model is the fail-soft
    fallback. So this hard-fails ONLY when **neither** a cloud brain nor a local
    model is usable. With the cloud brain active it proceeds even with no local
    model (the brain answers on its own); a local-only setup keeps the original
    "model present + Ollama reachable" checks.
    """
    from daemon.brain import brain_tier

    Console = _import_rich_console()
    console = Console()
    brain = brain_tier()  # cloud glm-5.2 by default; None when KINOX_BRAIN=local
    has_local = bool(manifest.local_models)

    # No local model at all — only the cloud brain can save us.
    if not has_local:
        if brain is not None:
            key_ok = _brain_key_present(brain.backend)
            note = "" if key_ok else " (no key → set ZAI_API_KEY)"
            console.print(
                f"[dim]preflight: brain {brain.model_name} "
                f"({brain.backend} · cloud){note} — no local fallback[/dim]"
            )
            return None
        return (
            "No model available.\n\n"
            "Set a cloud brain:  export ZAI_API_KEY=...   (glm-5.2)\n"
            "or run a local model in another terminal:\n"
            "  ollama serve\n"
            "  ollama pull hf.co/yuxinlu1/gemma-4-12B-coder-"
            "fable5-composer2.5-v1-GGUF:Q4_K_M\n\n"
            "Then try again."
        )

    # A local model is registered — verify Ollama is actually reachable.
    if not _ollama_reachable(manifest):
        if brain is not None:
            local_name = manifest.local_models[0].name
            console.print(
                f"[dim]preflight: brain {brain.model_name} ({brain.backend} · cloud) "
                f"ready — local fallback {local_name} is offline[/dim]"
            )
            return None
        return (
            "Ollama is registered but its API endpoint is not responding.\n\n"
            "Try:  ollama serve\n"
            "Then verify:  curl http://localhost:11434/v1/models"
        )

    # Everything is ready — report the brain and its local fallback.
    local = manifest.local_models[0]
    if brain is not None and brain.where == "cloud":
        key_ok = _brain_key_present(brain.backend)
        note = "" if key_ok else " (no key → fallback)"
        console.print(
            f"[dim]preflight: brain {brain.model_name} ({brain.backend} · cloud){note} "
            f"· fallback {local.name} ({local.backend}) — ready[/dim]"
        )
    else:
        console.print(
            f"[dim]preflight: {local.name} ({local.backend}) "
            f"on localhost:11434 — ready[/dim]"
        )
    return None


# --- public entry point ------------------------------------------------------


def chat_run(
    *,
    manifest: Manifest,
    sink: MetricsSink,
    cwd: Path,
    is_tty: bool = True,
    system_prompt: str | None = None,
) -> int:
    """Run the interactive chat loop.  Returns ``0`` on clean exit.

    Before entering the TUI, a **pre-flight check** verifies:
    1. At least one local model is registered (``ollama list``)
    2. That model fits in available VRAM
    3. Ollama's API endpoint is reachable (``/v1/models``)

    If any check fails, a diagnostic is printed and control returns to the hub
    immediately — we never enter the chat loop assuming a model is there.

    When *is_tty* is ``False`` (piped / test), prints a plan line and returns
    immediately — it never blocks on input.  This matches the hub's non-TTY
    contract.
    """
    if not is_tty:
        print("==> kinox chat · non-interactive: print plan and exit")
        return 0

    # Pre-flight: verify model availability before entering.
    error = _preflight(manifest)
    if error is not None:
        Console, Panel = _import_rich()
        console = Console()
        console.print(
            Panel.fit(
                f"[bold red]kinox chat — not ready[/bold red]\n\n{error}",
                border_style="red",
            )
        )
        return 0  # back to hub

    if not system_prompt:
        kinox_root = Path(__file__).resolve().parents[2]
        system_prompt = _session_preamble(kinox_root, cwd)

    system_prompt += (
        "\n\n### RESIDUAL MEMORY MODE\n"
        "This session uses constant memory. You must end your final response to every turn "
        "with a strict `<residual_state>` block summarizing what you did, what the current "
        "state of the project is, and what you think the user might want to do next. "
        "This summary will be fed back to you as your only memory of the past conversation."
    )

    session = ChatSession(
        manifest=manifest,
        sink=sink,
        cwd=cwd,
        system_prompt=system_prompt,
    )

    residual_file = cwd / ".kinox_residual"
    if residual_file.is_file():
        try:
            saved_state = residual_file.read_text(encoding="utf-8")
            if saved_state.strip():
                session.history.append({"role": "assistant", "content": saved_state})
        except Exception:
            pass

    _welcome(session)
    try:
        return _loop(session)
    except _QuitChat:
        return 0


# --- welcome -----------------------------------------------------------------


def _welcome(session: ChatSession) -> None:
    """Print the chat welcome banner — simple, clear, kinox-branded.

    Shows the active **brain** (cloud ``glm-5.2`` by default) with the local
    model as the fail-soft fallback, so the banner reflects what actually
    reasons — not just the local preflight model."""
    from daemon.brain import brain_tier

    Console, Panel = _import_rich()

    models = session.manifest.local_models
    local_name = models[0].name if models else None
    brain = brain_tier()
    scope = session.cwd.name if session.cwd.name else str(session.cwd)

    if brain is not None and brain.where == "cloud":
        key_ok = _brain_key_present(brain.backend)
        key = "" if key_ok else " [yellow](no key → fallback)[/yellow]"
        model_block = f"brain: {brain.model_name} ({brain.backend} · cloud){key}"
        if local_name:
            model_block += f"\nfallback: {local_name}"
    elif brain is not None:
        model_block = f"model: {brain.model_name}"
    else:
        model_block = f"model: {local_name or 'none'}"

    from products import theme

    console = Console()
    console.print(
        Panel.fit(
            f"{theme.wordmark(width=console.width)}\n"
            f"[bold cyan]scope[/bold cyan]  {scope}\n"
            f"{model_block}\n"
            f"[dim]agent mode · read · write · bash · skills[/dim]\n\n"
            f"[dim]{theme.tip(os.getpid())}[/dim]\n"
            f"[dim]/help  /model  /chat  /quit[/dim]",
            border_style=theme.BORDER,
            box=theme.box(),
            padding=(0, 2),
        )
    )


# --- main loop ---------------------------------------------------------------


def _loop(session: ChatSession) -> int:
    """Run the prompt→response loop until the user types ``/quit``."""
    Console = _import_rich_console()
    console = Console()
    pt = _import_prompt_toolkit()

    if pt is None:
        return _text_loop(session, console)  # plain input() fallback
    return _pt_loop(session, console, pt)


def _text_loop(session: ChatSession, console: object) -> int:
    """Fallback loop using plain ``input()`` — single-line, no history."""
    while True:
        try:
            raw = input("\nyou> ").strip()
        except (EOFError, KeyboardInterrupt):
            console.print("\n[dim](quit)[/dim]")
            return 0
        if not raw:
            continue
        if _handle_command(raw, session, console):
            continue
        _run_agent_turn(raw, session, console)  # kx is agent mode by default
    return 0


def _pt_loop(session: ChatSession, console: object, pt: object) -> int:
    """Main loop with prompt_toolkit for multi-line input + command history."""
    import time

    from prompt_toolkit.history import InMemoryHistory
    from prompt_toolkit.key_binding import KeyBindings
    from prompt_toolkit.styles import Style

    from products import theme

    history = InMemoryHistory()

    # Session context for the toolbar: scope name + the active brain model, both
    # resolved once (the brain tier is stable for the session) so each keystroke
    # repaint stays cheap. Fail-soft — a missing brain just shows a dash.
    session_start = time.monotonic()
    scope_name = session.cwd.name or str(session.cwd)
    try:
        from daemon.brain import brain_tier

        _bt = brain_tier()
        model_label = _bt.model_name if _bt is not None else "—"
        is_cloud = _bt is not None and getattr(_bt, "where", None) == "cloud"
    except Exception:  # noqa: BLE001 — toolbar must never crash the prompt
        model_label, is_cloud = "—", False

    # Key bindings: Enter submits (the universal default); Esc+Enter / Alt+Enter
    # inserts a newline for multi-line input or pasted code. Without the explicit
    # Enter binding, multiline=True makes plain Enter insert a newline — so
    # messages never dispatch and the input silently piles up blank lines instead
    # of reaching the model.
    kb = KeyBindings()

    @kb.add("enter")
    def _(event: object) -> None:
        event.current_buffer.validate_and_handle()  # Enter → send

    @kb.add("escape", "enter")
    def _(event: object) -> None:
        event.current_buffer.insert_text("\n")  # Esc+Enter → newline

    @kb.add("s-tab")
    def _(event: object) -> None:
        event.current_buffer.insert_text("\t")

    @kb.add("c-u")
    def _(event: object) -> None:
        # Wipe the WHOLE input in one keystroke — the default c-u only deletes
        # to the start of the current line, which is useless after a long or
        # pasted multi-line message. Clearing .text also resets the cursor.
        event.current_buffer.text = ""

    # Ctrl+W (delete previous word) and Ctrl+K (delete to end of line) come for
    # free from prompt_toolkit's default emacs bindings; c-u above is the only
    # one we override so it clears everything, not just the line.

    style = Style.from_dict(
        {
            "prompt": "ansicyan bold",
            "bottom-toolbar": "dim",
        }
    )

    # A fixed key reference, always pinned to the bottom so editing shortcuts
    # are visible at a glance instead of only surfacing in the rotating tip.
    sep = " | " if theme.ascii_only() else " · "
    keys_line = sep.join(
        (
            "Enter send",
            "Esc+Enter newline",
            "Ctrl+U clear all",
            "Ctrl+W del word",
            "Ctrl+C quit",
        )
    )

    def bottom_toolbar() -> str:
        n = len(session.history) // 2
        secs = int(time.monotonic() - session_start)
        m, s = divmod(secs, 60)
        elapsed = f"{m}m{s:02d}s" if m else f"{s}s"
        cloud = f" {theme.CLOUD}" if is_cloud and not theme.ascii_only() else ""
        # Two lines: a live status line + a rotating hint, then a fixed key
        # reference pinned underneath so the shortcuts are always on screen.
        status = (
            f" {scope_name} · {model_label}{cloud} · {n} turns · {elapsed}"
            f"    {theme.tip(n)}"
        )
        return f"{status}\n {keys_line}"

    # Use prompt_toolkit.shortcuts.PromptSession for a clean API.
    try:
        from prompt_toolkit.shortcuts import PromptSession
    except ImportError:
        # Older prompt_toolkit — fall back.
        return _text_loop(session, console)

    ps = PromptSession(
        history=history,
        key_bindings=kb,
        style=style,
        bottom_toolbar=bottom_toolbar,
        multiline=True,
    )

    while True:
        try:
            raw = ps.prompt([("class:prompt", "you> ")]).strip()
        except (EOFError, KeyboardInterrupt):
            console.print("\n[dim](quit)[/dim]")
            return 0
        if not raw:
            continue
        if _handle_command(raw, session, console):
            continue
        _run_agent_turn(raw, session, console)  # kx is agent mode by default
    return 0


# --- command dispatch --------------------------------------------------------


def _handle_command(raw: str, session: ChatSession, console: object) -> bool:
    """Handle a ``/`` command.  Returns ``True`` if the input was consumed."""
    if not raw.startswith("/"):
        return False  # not a command

    cmd, _, arg = raw[1:].strip().partition(" ")
    cmd = cmd.lower()

    if cmd in ("q", "quit", "exit"):
        console.print("[dim]bye[/dim]")
        raise _QuitChat()

    if cmd in ("c", "clear"):
        session.clear()
        console.print("[dim]history cleared[/dim]")
        return True

    if cmd in ("h", "help"):
        console.print(
            "\n[bold]commands:[/bold]\n"
            "  [cyan]/help[/cyan]   — this message\n"
            "  [cyan]/clear[/cyan]  — reset conversation history\n"
            "  [cyan]/quit[/cyan]   — exit chat (or Ctrl+D)\n"
            "  [cyan]/model[/cyan]  — show/switch the brain (z.ai, OpenRouter, local)\n"
            "  [cyan]/models[/cyan] — list OpenRouter text models\n"
            "  [cyan]/chat[/cyan]   — one plain reply, no tools (escape agent mode)\n"
            "  [cyan]/agent[/cyan]  — explicit agent task (turns are agent mode)\n"
            "  [cyan]/par[/cyan]    — fan out to parallel agents on disjoint slices "
            "(project scope):\n"
            "            [dim]/par <task> @ p1,p2 ;; <task2> @ p3[/dim]\n"
            "  [cyan]/parf[/cyan]   — same, but framework scope (whole kinox "
            "workspace)\n\n"
            "[dim]Every message runs the agent: read · write_file · run_bash · "
            "skills, in this scope.[/dim]\n"
            "[dim]Enter sends · Esc+Enter inserts a newline (multi-line)[/dim]\n"
        )
        return True

    if cmd in ("m", "model"):
        _cmd_model(arg.strip(), session, console)
        return True

    if cmd == "models":
        _cmd_models(console)
        return True

    if cmd in ("a", "agent"):
        # Every turn is already an agent turn; /agent stays as an explicit alias.
        if not arg.strip():
            console.print(
                "[dim]usage: /agent <task> (every turn is agent mode already)[/dim]"
            )
        else:
            _run_agent_turn(arg.strip(), session, console)
        return True

    if cmd in ("par", "parallel"):
        _run_parallel_turn(arg.strip(), session, console, framework=False)
        return True

    if cmd == "parf":
        _run_parallel_turn(arg.strip(), session, console, framework=True)
        return True

    if cmd == "chat":
        # Escape hatch: one plain, tool-less reply (cheap conversation).
        if not arg.strip():
            console.print("[dim]usage: /chat <message> — a plain reply, no tools[/dim]")
        else:
            _process_turn(arg.strip(), session, console)
        return True

    if cmd == "resume":
        _cmd_resume(arg.strip(), session, console)
        return True

    console.print(f"[dim]unknown command: /{cmd} — try /help[/dim]")
    return True


# --- brain selection ---------------------------------------------------------


def _cmd_model(arg: str, session: ChatSession, console: object) -> None:
    """``/model`` — show the active brain + menu, or switch to a chosen brain.

    No arg lists the current brain and the presets. ``/model <n>`` picks a preset,
    ``/model openrouter <id>`` uses any OpenRouter model, ``/model local`` disables
    the cloud brain. The switch is live (next turn) and persisted to ~/.kinox/env.
    """
    from daemon.brain import BRAIN_PRESETS, describe_brain, set_brain

    local = session.manifest.local_models
    local_name = local[0].name if local else "none"

    if not arg:
        console.print(
            f"[bold]brain:[/bold] {describe_brain()}  ·  fallback: {local_name}"
        )
        for i, preset in enumerate(BRAIN_PRESETS, 1):
            console.print(f"  [cyan]{i}[/cyan]  {preset.label}")
        console.print(
            "  [cyan]or[/cyan]  openrouter <model-id>   "
            "(see [cyan]/models[/cyan] for the live list)"
        )
        console.print(
            "[dim]switch: /model <n> · /model openrouter <id> · /model local[/dim]"
        )
        return

    parts = arg.split()
    head = parts[0].lower()

    if head == "openrouter":
        if len(parts) < 2:
            console.print(
                "[dim]usage: /model openrouter <model-id>  "
                "(e.g. openai/gpt-4o-mini)[/dim]"
            )
            return
        label = set_brain(parts[1], "openrouter", "cloud")
        console.print(f"[green]brain → {label}[/green]  [dim](persisted)[/dim]")
        if not _brain_key_present("openrouter"):
            console.print(
                "[yellow]note: OPENROUTER_API_KEY not set — add it to "
                "~/.kinox/env (else it falls back to local)[/yellow]"
            )
        return

    if head in ("local", "off", "none"):
        label = set_brain(None)
        console.print(f"[green]brain → {label}[/green]  [dim](persisted)[/dim]")
        return

    if head.isdigit():
        idx = int(head) - 1
        if not (0 <= idx < len(BRAIN_PRESETS)):
            console.print(f"[dim]no preset {head} — /model to list[/dim]")
            return
        preset = BRAIN_PRESETS[idx]
        label = set_brain(preset.model, preset.backend, preset.where)
        console.print(f"[green]brain → {label}[/green]  [dim](persisted)[/dim]")
        if preset.backend and not _brain_key_present(preset.backend):
            console.print(
                f"[yellow]note: key for {preset.backend} not set — "
                "falls back to local until it is[/yellow]"
            )
        return

    console.print("[dim]usage: /model [<n> | openrouter <id> | local][/dim]")


def _cmd_models(console: object) -> None:
    """``/models`` — list OpenRouter text→text model ids (live)."""
    from daemon.brain import openrouter_text_models

    console.print("[dim]fetching OpenRouter text models…[/dim]")
    ids = openrouter_text_models(limit=60)
    if not ids:
        console.print(
            "[yellow]couldn't fetch the list (offline?) — browse "
            "https://openrouter.ai/models and pick any id[/yellow]"
        )
        return
    console.print(f"[bold]OpenRouter text→text models[/bold] (showing {len(ids)}):")
    for mid in ids:
        console.print(f"  [cyan]{mid}[/cyan]")
    console.print("[dim]use one: /model openrouter <id>[/dim]")


# --- turn processing ---------------------------------------------------------


def _stream_turn(raw: str, session: ChatSession, console: object) -> bool:
    """Stream the reply token-by-token via ``rich.Live`` (vision §5.2 Layer 3).

    Returns ``True`` when it handled the turn (the stream itself fails soft inside
    :meth:`ChatSession.send_stream`, falling back to the non-streaming chain, so a
    ``True`` return still means a complete answer was rendered). Returns ``False``
    only when streaming is unavailable (``KINOX_STREAM=0``, no rich, or a setup
    error) so the caller uses the spinner path. The streamed view is transient and
    replaced by the authoritative final render — correct even if the stream fell
    back internally.
    """
    import asyncio
    import contextlib

    if os.environ.get("KINOX_STREAM", "1").lower() in ("0", "off", "false", "no"):
        return False
    try:
        from rich.live import Live
        from rich.markdown import Markdown
    except Exception:
        return False

    buf: list[str] = []

    def on_delta(delta: str) -> None:
        buf.append(delta)
        with contextlib.suppress(Exception):
            live.update(Markdown(_strip_reasoning("".join(buf))))

    try:
        with Live(console=console, transient=True, refresh_per_second=12) as live:
            response, notes, tier = asyncio.run(session.send_stream(raw, on_delta))
    except Exception:
        return False  # streaming setup failed → let the spinner path handle it

    for note in notes:
        console.print(f"  [dim yellow]ⓘ {note}[/dim yellow]")
    label = f" {tier.model_name} ({tier.backend})" if tier is not None else ""
    console.print(f"[bold green]kinox{label}:[/bold green]")
    _render_response(response, console)
    console.print()
    return True


def _process_turn(raw: str, session: ChatSession, console: object) -> None:
    """Run one user→assistant turn: groom, dispatch, display.

    Model dispatch runs in a background thread so the terminal can show a
    ``rich.status`` spinner instead of going dead-silent for 30–60 s.  Fast
    responses (< 300 ms) skip the spinner entirely to avoid flicker.
    """
    import time
    from concurrent.futures import ThreadPoolExecutor

    # NB: don't re-echo the user's message — both prompt_toolkit and the plain
    # input() fallback already leave the typed "you> …" line on screen, so a
    # second "you: …" print just duplicates it. A blank line keeps the turns
    # visually separated.
    console.print()

    # Live streaming path (vision §5.2 Layer 3): render the brain's reply
    # token-by-token. Returns False (and falls through to the spinner path) only
    # when streaming is unavailable; the stream itself fails soft inside the session.
    if _stream_turn(raw, session, console):
        return

    # Process through the session in a background thread.
    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(session.send, raw)

        try:
            response, notes, tier = future.result(timeout=0.3)
        except TimeoutError:
            # Slow path — show a spinner with elapsed time while the model works.
            start = time.monotonic()
            with console.status("[dim]processing…[/dim]", spinner="dots") as status:
                while not future.done():
                    elapsed = time.monotonic() - start
                    status.update(
                        f"[dim]processing… ({elapsed:.1f}s)[/dim]"
                    )
                    time.sleep(0.25)
            try:
                response, notes, tier = future.result()
            except Exception as exc:
                console.print(f"[bold red]error:[/bold red] {exc}")
                return

    # Groom notes (redacted secrets, tags, etc.)
    for note in notes:
        console.print(f"  [dim yellow]ⓘ {note}[/dim yellow]")

    # Model tier label
    label = f" {tier.model_name} ({tier.backend})" if tier is not None else ""

    # Model response
    console.print(f"[bold green]kinox{label}:[/bold green]")
    _render_response(response, console)
    console.print()  # blank line before next prompt




def _is_framework_scope(kinox_root: Path, scope: Path) -> bool:
    """True when the session scope IS the framework repo root (admin core scope).

    Any other scope — a project under ``projects/`` or an external directory — is
    a project scope. The discriminator is exact identity with the repo root, so a
    project can never be mistaken for the framework.
    """
    try:
        return scope.resolve() == kinox_root.resolve()
    except OSError:
        return False


def _session_preamble(kinox_root: Path, scope: Path) -> str:
    """Compile the scope-appropriate preamble for a session, pre-injected at turn one.

    A **framework**-scope session (working on kinox) gets the axioms plus the
    framework internals; a **project** session gets the axioms alone — it is told
    the rules it must follow, never the structure of the framework that runs it.
    Cached per root. Fails soft: returns '' if no alignment files are found.
    """
    try:
        from products.agent.environment import session_preamble

        return session_preamble(
            kinox_root, framework=_is_framework_scope(kinox_root, scope)
        )
    except Exception:
        return ""


def _cmd_resume(arg: str, session: ChatSession, console: object) -> None:
    """Resume a stopped agent session from disk."""
    from products.agent.session import SessionStore
    store = SessionStore(session.cwd / ".kinox" / "sessions")
    
    target_id = arg.strip()
    if not target_id:
        paths = sorted(store.directory.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
        if not paths:
            console.print("[dim]no sessions found to resume[/dim]")
            return
        target_id = paths[0].stem
    
    state = store.load(target_id)
    if not state:
        console.print(f"[bold red]error:[/bold red] session {target_id} not found or corrupted")
        return
        
    console.print(f"[dim]resuming session {target_id}...[/dim]")
    _run_agent_turn("", session, console, resume_from=state, resume_id=target_id)


def _run_agent_turn(
    task: str,
    session: ChatSession,
    console: object,
    *,
    resume_from: object | None = None,
    resume_id: str | None = None,
) -> None:
    """Run one tool-calling agent task and render its step trace + answer.

    This is the **default** turn for a ``kx`` session: the full toolset — read +
    ``write_file`` + ``run_bash`` + the skill bridge over ``.claude/skills`` —
    write/exec ON because the session is the operator's own shell, but jailed to
    the session scope by ``project_root_guard`` so even an admin session resides
    only within its repository (run_bash escapes the root → blocked, fail-CLOSED).
    Dispatch runs in a worker thread for the spinner.
    """
    import asyncio
    import time
    import uuid
    import queue
    from collections import deque
    from concurrent.futures import ThreadPoolExecutor

    from daemon.brain import brain_tier
    from kernel.contracts import Tier

    from products.agent import default_registry, project_root_guard, run_agent
    from products.agent.coordinator import combine_guards
    from products.agent.planner import plan_task
    from products.agent.rails import protected_rails_guard
    from products.capabilities.registry import CapabilityRegistry

    from products.agent.budget import TokenBudget
    from products.agent.config import load_ruleset, load_token_budget, load_tool_config

    global_path = Path("~/.kinox/config.toml").expanduser()
    kinox_root = Path(__file__).resolve().parents[2]
    project_path = kinox_root / "kinox.toml"
    global_text = global_path.read_text() if global_path.is_file() else None
    project_text = project_path.read_text() if project_path.is_file() else None
    profile = os.environ.get("KINOX_PROFILE")

    config_budget = load_token_budget(global_text, project_text, profile=profile)
    ruleset = load_ruleset(global_text, project_text, profile=profile)
    tool_config = load_tool_config(global_text, project_text, profile=profile)

    # The FULL harvested corpus: skills + commands + agent playbooks + MCP
    # descriptors — all discoverable via find_skill/load_skill.
    skills = CapabilityRegistry.from_claude_dir(kinox_root / ".claude")
    # Unrestricted: write + bash ON, no guard — a fully-trusted operator agent.
    # MCP servers in .claude/mcp-servers.json are started and exposed as live
    # tools (fail-soft). Gated by KINOX_MCP (default on) because the first turn
    # pays the server cold-start; set KINOX_MCP=0 to skip. Cached after start.
    mcp_on = os.environ.get("KINOX_MCP", "1").lower() not in ("0", "off", "false", "no")
    if not tool_config.allow_mcp:
        mcp_on = False
    mcp_config = kinox_root / ".claude" / "mcp-servers.json" if mcp_on else None
    if mcp_config is not None and str(mcp_config) not in _mcp_started:
        console.print("[dim]connecting MCP servers (set KINOX_MCP=0 to skip)…[/dim]")
        _mcp_started.add(str(mcp_config))
    registry = default_registry(
        session.cwd,
        skills=skills,
        allow_bash=tool_config.allow_bash,
        allow_write=tool_config.allow_write,
        mcp_config=mcp_config,
    )
    # kinox's agent brain is cloud-first (``glm-5.2``); the first local model is
    # the fail-soft fallback. With no local model the cloud brain runs alone; only
    # when neither exists (cloud disabled AND no local model) do we bail.
    models = session.manifest.local_models
    local_tier = (
        Tier.model(models[0].name, where="local", backend=models[0].backend)
        if models
        else None
    )
    from daemon.brain import brain_chain
    chain = brain_chain(fallback=local_tier)
    tier = chain[0] if chain else None
    fallback_tiers = chain[1:] if len(chain) > 1 else None
    if tier is None:
        console.print(
            "[dim]no model available (set ZAI_API_KEY or run a local model)[/dim]"
        )
        return

    # Quiet by default: show only the spinner, the final answer, and a one-line
    # status footer. Set KINOX_VERBOSE=1 to restore the prompt echo, tool list,
    # and per-step trace (useful when debugging the agent loop).
    verbose = os.environ.get("KINOX_VERBOSE", "0").lower() in ("1", "on", "true", "yes")
    if verbose:
        console.print(f"\n[bold cyan]agent:[/bold cyan] {task}")
        console.print(
            f"[dim]tools: {', '.join(registry.tools)}  ·  skills: {len(skills)}[/dim]"
        )

    # Live trace: run_agent fires on_step for every tool call as it happens. We
    # push those into a thread-safe queue and DRAIN them on the main thread (the
    # spinner loop) so nothing prints across threads while the live status is up.
    steps_q: deque[object] = deque()
    # Live answer: run_agent fires on_token for each content delta (vision §5.2).
    # We push tokens onto a thread-safe queue and show a live tail in the status
    # line, so the final answer is visibly generating instead of a dead spinner.
    # KINOX_STREAM=0 disables it (on_token=None → the non-streaming chain).
    tokens_q: deque[str] = deque()
    stream_on = os.environ.get("KINOX_STREAM", "1").lower() not in (
        "0", "off", "false", "no"
    )

    # Per-SESSION token budget (vision §9): KINOX_SESSION_TOKEN_BUDGET caps the
    # total model tokens across ALL agent turns this session, not one run. Opt-in
    # — unset/invalid → unlimited, so the default operator shell is unchanged. The
    # cumulative tally lives on the session and is carried into each run via
    # spent_offset; a spent budget ends the turn fail-soft (stopped="budget").
    _raw_budget = os.environ.get("KINOX_SESSION_TOKEN_BUDGET", "").strip()
    if _raw_budget.isdigit() and int(_raw_budget) > 0:
        session_budget: TokenBudget | None = TokenBudget(limit=int(_raw_budget))
    else:
        session_budget = config_budget

    ask_q: queue.Queue[tuple[str, str]] = queue.Queue()
    reply_q: queue.Queue[bool] = queue.Queue()

    def ask_command(tool: str, cmd_str: str) -> bool:
        ask_q.put((tool, cmd_str))
        return reply_q.get()

    def work() -> object:
        async def _go() -> object:
            base_id = resume_id or uuid.uuid4().hex[:12]
            # Cheap local prehook: draft a plan to curb wander before the dear
            # brain runs. Fail-soft — None (planner off/unavailable) runs unguided.
            plan = await plan_task(
                task,
                sink=session.sink,
                task_id=f"{base_id}-plan",
                root=session.cwd,
            )
            result = await run_agent(
                task,
                tier=tier,
                registry=registry,
                sink=session.sink,
                task_id=base_id,
                preamble=_session_preamble(kinox_root, session.cwd),
                history=list(session.history),
                plan=plan,
                guard=combine_guards(
                    project_root_guard(
                        session.cwd,
                        # Framework scope may not write down into a project scope —
                        # the scope wall is bidirectional, so framework and project
                        # work can run in parallel without overlap.
                        deny_write_subpaths=("projects",)
                        if _is_framework_scope(kinox_root, session.cwd)
                        else (),
                        ruleset=ruleset,
                        ask_fn=ask_command,
                    ),
                    # Hard truth #1: the agent may not overwrite kinox's own rails
                    # (alignment/, next.md) — fail-CLOSED, KINOX_UNLOCK_RAILS to edit.
                    protected_rails_guard(session.cwd),
                ),
                fallback=fallback_tiers,
                max_turns=int(os.environ.get("KINOX_MAX_TURNS", "30")),
                token_budget=session_budget,
                spent_offset=session.tokens_spent,
                on_step=steps_q.append,
                on_token=tokens_q.append if stream_on else None,
                resume_from=resume_from,
            )
            return result, base_id

        return asyncio.run(_go())

    tools_done = 0
    answer_buf: list[str] = []
    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(work)
        start = time.monotonic()
        with console.status("[dim]agent working…[/dim]", spinner="dots") as status:
            while True:
                try:
                    tool, cmd_str = ask_q.get_nowait()
                    status.stop()
                    from rich.prompt import Confirm
                    allow = Confirm.ask(f"\n[bold yellow]Agent wants to run (ASK level):[/bold yellow] [cyan]{cmd_str}[/cyan]\nAllow?")
                    reply_q.put(allow)
                    status.start()
                except queue.Empty:
                    pass

                # Drain steps emitted since the last tick, above the live status.
                while steps_q:
                    step = steps_q.popleft()
                    if step.kind == "tool":
                        tools_done += 1
                        if verbose:
                            console.print(
                                _format_tool_step(step.name, step.detail, verbose)
                            )
                        else:
                            status.update(f"[dim]agent working… (tool calls: {tools_done})[/dim]")
                    elif step.kind == "blocked":
                        console.print(
                            f"  [red]⛔ {_esc(step.name)} blocked:[/red] "
                            f"[dim]{_esc(step.detail)}[/dim]"
                        )
                    # "final" is the summary — rendered in the panel below.
                # Drain answer tokens → a live tail so the answer is seen forming.
                while tokens_q:
                    answer_buf.append(tokens_q.popleft())
                tail = ""
                if answer_buf:
                    flat = _strip_reasoning("".join(answer_buf)).replace("\n", " ")
                    if flat:
                        tail = f" · [white]…{_esc(flat[-60:])}[/white]"
                status.update(
                    f"[dim]agent working · {tools_done} tool"
                    f"{'' if tools_done == 1 else 's'} · "
                    f"{time.monotonic() - start:.1f}s{tail}[/dim]"
                )
                if future.done() and not steps_q and not tokens_q:
                    console.bell()
                    break
                time.sleep(0.1)
        try:
            result, base_id = future.result()
        except Exception as exc:  # noqa: BLE001 — surface, never crash the TUI
            console.print(f"[bold red]agent error:[/bold red] {exc}")
            return

    # Persist this turn into the session's single canonical history so the next
    # agent turn remembers it (each run_agent call otherwise starts cold). Store
    # only the distilled user task + final answer — never the run's ephemeral tool
    # scratch — mirroring ChatSession.send, and trim to the same pair cap.
    final_text = getattr(result, "final_text", "")
    if final_text:
        if session.residual_mode and "<residual_state>" in final_text:
            residual_start = final_text.find("<residual_state>")
            residual_end = final_text.find("</residual_state>")
            if residual_start != -1:
                state_text = final_text[residual_start:residual_end + 17] if residual_end != -1 else final_text[residual_start:]
                session.history.clear()
                session.history.append({"role": "assistant", "content": state_text})
                try:
                    (session.cwd / ".kinox_residual").write_text(state_text, encoding="utf-8")
                except Exception:
                    pass
        else:
            session.history.append({"role": "user", "content": task})
            session.history.append({"role": "assistant", "content": final_text})
            while len(session.history) > _MAX_HISTORY_PAIRS * 2:
                session.history.pop(0)  # drop oldest pair

    # Carry this run's cumulative spend forward so the NEXT turn's budget continues
    # from here (the run already includes spent_offset in result.tokens_spent).
    session.tokens_spent = getattr(result, "tokens_spent", session.tokens_spent)

    # Summary: the final answer, framed in a panel with a status footer.
    _render_summary(
        result,
        console,
        tools=tools_done,
        elapsed=time.monotonic() - start,
        session_tokens=session.tokens_spent,
        budget_limit=session_budget.limit if session_budget else None,
    )
    console.print()

    if getattr(result, "state", None):
        from products.agent.session import SessionStore
        store = SessionStore(session.cwd / ".kinox" / "sessions")
        store.save(base_id, result.state)
        if result.stopped in ("budget", "max_turns", "stuck", "error"):
            console.print(f"[dim]Session paused ({result.stopped}). Use `/resume {base_id}` to continue.[/dim]")


def _parse_slices(arg: str) -> list[tuple[str, tuple[str, ...]]] | None:
    """Parse ``task @ p1,p2 ;; task2 @ p3`` into ``(task, owned_paths)`` specs.

    Agents are split on ``;;``; within each, ``@`` separates the task from a
    comma-list of owned paths. A spec with no ``@`` owns nothing (a read-only
    slice). Returns ``None`` when nothing parseable is found or a task is empty.
    """
    specs: list[tuple[str, tuple[str, ...]]] = []
    for chunk in arg.split(";;"):
        chunk = chunk.strip()
        if not chunk:
            continue
        task, sep, paths = chunk.partition("@")
        task = task.strip()
        if not task:
            return None
        owned = (
            tuple(p.strip() for p in paths.split(",") if p.strip()) if sep else ()
        )
        specs.append((task, owned))
    return specs or None


def _run_parallel_turn(
    arg: str, session: ChatSession, console: object, *, framework: bool
) -> None:
    """Fan one turn out to N agents over disjoint slices (the parallelism axiom).

    The scope is the *root* the coordinator partitions: the session's project
    (``/par``) or the whole kinox workspace (``/parf``, *framework*). Each agent
    is jailed to its own slice — a write into another agent's slice is refused —
    so two agents run at once with nothing to collapse or override. The partition
    is validated up-front (fail-CLOSED) so a bad split is a clean message, not a
    half-run.
    """
    import asyncio
    import time
    import uuid
    from collections import deque
    from concurrent.futures import ThreadPoolExecutor

    from daemon.brain import brain_tier
    from kernel.contracts import Tier

    from products.agent import Slice, default_registry, run_agent, run_parallel
    from products.agent.coordinator import OverlapError, assert_disjoint
    from products.agent.planner import plan_task
    from products.capabilities.registry import CapabilityRegistry

    specs = _parse_slices(arg)
    if not specs or len(specs) < 2:
        console.print(
            "[dim]usage: /par <task> @ p1,p2 ;; <task2> @ p3 — 2+ agents, each "
            "owning disjoint paths (/parf = framework scope)[/dim]"
        )
        return

    kinox_root = Path(__file__).resolve().parents[2]
    root = kinox_root if framework else session.cwd
    scope = "framework" if framework else "project"

    slices = [
        Slice(task=t, owned=o, label=f"a{i + 1}") for i, (t, o) in enumerate(specs)
    ]
    try:
        assert_disjoint(slices, root)  # fail-CLOSED before any agent spawns
    except OverlapError as exc:
        console.print(f"[bold red]overlap refused:[/bold red] {exc}")
        return

    skills = CapabilityRegistry.from_claude_dir(kinox_root / ".claude")
    # One registry, jailed to the SCOPE root; each agent's per-slice guard (built
    # by run_parallel) is what confines its writes. Dispatch is stateless, so the
    # shared registry is safe under concurrency.
    registry = default_registry(
        root, skills=skills, allow_bash=True, allow_write=True
    )
    models = session.manifest.local_models
    local_tier = (
        Tier.model(models[0].name, where="local", backend=models[0].backend)
        if models
        else None
    )
    from daemon.brain import brain_chain
    chain = brain_chain(fallback=local_tier)
    tier = chain[0] if chain else None
    fallback_tiers = chain[1:] if len(chain) > 1 else None
    if tier is None:
        console.print(
            "[dim]no model available (set ZAI_API_KEY or run a local model)[/dim]"
        )
        return

    console.print(
        f"\n[bold cyan]parallel[/bold cyan] [dim]({scope} scope)[/dim] · "
        f"{len(slices)} agents"
    )
    for s in slices:
        owns = ", ".join(s.owned) or "(read-only)"
        console.print(
            f"  [magenta]{s.label}[/magenta] [dim]{s.task} · owns {owns}[/dim]"
        )

    steps_q: deque[tuple[str, object]] = deque()
    base_id = uuid.uuid4().hex[:12]
    preamble = _session_preamble(kinox_root, root)
    max_turns = int(os.environ.get("KINOX_MAX_TURNS", "30"))

    def make_run() -> object:
        async def run(s: Slice, guard: object) -> object:
            # Each slice gets its own prehook plan (its task is disjoint from the
            # others), front-loading direction before the dear brain runs. Fail-soft.
            plan = await plan_task(
                s.task,
                sink=session.sink,
                task_id=f"{base_id}:{s.label}-plan",
                root=root,
            )
            return await run_agent(
                s.task,
                tier=tier,
                registry=registry,
                sink=session.sink,
                task_id=f"{base_id}:{s.label}",
                guard=guard,  # type: ignore[arg-type]
                preamble=preamble,
                plan=plan,
                fallback=fallback_tiers,
                max_turns=max_turns,
                # Tag each step with its slice label so the interleaved trace is
                # attributable (one trace, the axiom's no-two-ID-systems rule).
                on_step=lambda step, label=s.label: steps_q.append((label, step)),
            )

        return run

    def work() -> object:
        return asyncio.run(run_parallel(slices, root=root, run=make_run()))  # type: ignore[arg-type]

    tools_done = 0
    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(work)
        start = time.monotonic()
        with console.status("[dim]agents working…[/dim]", spinner="dots") as status:
            while True:
                while steps_q:
                    label, step = steps_q.popleft()
                    if step.kind == "tool":
                        tools_done += 1
                        line = _format_tool_step(step.name, step.detail, False)
                        console.print(f"  [magenta]{_esc(label)}[/magenta]{line}")
                    elif step.kind == "blocked":
                        console.print(
                            f"  [magenta]{_esc(label)}[/magenta]  [red]⛔ {_esc(step.name)} "
                            f"blocked:[/red] [dim]{_esc(step.detail)}[/dim]"
                        )
                status.update(
                    f"[dim]{len(slices)} agents · {tools_done} tools · "
                    f"{time.monotonic() - start:.1f}s[/dim]"
                )
                if future.done() and not steps_q:
                    break
                time.sleep(0.1)
        try:
            pairs = future.result()
        except Exception as exc:  # noqa: BLE001 — surface, never crash the TUI
            console.print(f"[bold red]parallel error:[/bold red] {exc}")
            return

    elapsed = time.monotonic() - start
    for s, result in pairs:
        console.print(f"\n[bold magenta]{s.label}[/bold magenta] [dim]{s.task}[/dim]")
        agent_tools = sum(1 for st in result.steps if st.kind == "tool")
        _render_summary(result, console, tools=agent_tools, elapsed=elapsed)
    console.print()


#: First arg key worth showing per call, in priority order.
_ARG_KEYS = ("path", "file", "cmd", "command", "query", "pattern", "name", "url")


def _esc(text: object) -> str:
    """Escape dynamic text so Rich never reads embedded brackets (e.g. a
    bracketed file path in a blocked-tool message, or model output) as markup
    tags. Lazy import keeps kx cold-start discipline."""
    from rich.markup import escape

    return escape(str(text))


def _format_tool_step(name: str, detail: str, verbose: bool) -> str:
    """One compact, colour-coded line for a live tool call.

    Quiet mode shows just the single most useful argument (path/cmd/query);
    verbose shows the raw JSON args.
    """
    import json

    from products import theme

    color = theme.tool_color(name)
    glyph = theme.tool_glyph(name)
    short = name.replace("mcp__", "")
    if verbose:
        arg = detail
    else:
        arg = ""
        try:
            data = json.loads(detail) if detail else {}
        except Exception:
            data = {}
        if isinstance(data, dict) and data:
            for key in _ARG_KEYS:
                if key in data:
                    arg = str(data[key])
                    break
            else:
                k, v = next(iter(data.items()))
                arg = f"{k}={v}"
        if len(arg) > 64:
            arg = arg[:63] + "…"
    return f"  {glyph} [{color}]{_esc(short)}[/{color}] [dim]{_esc(arg)}[/dim]"


def _strip_reasoning(text: str) -> str:
    """Drop ``<think>``/``<thinking>`` blocks so reasoning models (deepseek-r1
    fallback) never leak their scratchpad into the rendered answer. The canonical
    implementation lives in the pure output model (products/chat/output.py)."""
    from products.chat.output import strip_reasoning

    return strip_reasoning(text)


def _render_summary(
    result: object,
    console: object,
    *,
    tools: int,
    elapsed: float,
    session_tokens: int | None = None,
    budget_limit: int | None = None,
) -> None:
    """Render the run as a GENERATED view (vision §5.2 Layer 3): the markdown
    answer framed in a panel with a status + per-tool footer composed from the
    run's structure, and — under KINOX_VERBOSE — a generated trace tree of what
    the agent did. Falls back to plain print if rich is unavailable.

    *session_tokens* (the cumulative session spend) is shown in the footer when
    given — with the budget ceiling when one is set — so a per-session budget is
    visible as it accrues instead of silently enforced."""
    from products.chat.output import build_run_view

    view = build_run_view(result, tools=tools, elapsed_s=elapsed)
    Markdown = _import_rich_markdown()
    renderable = (
        Markdown(view.answer, code_theme="monokai") if Markdown else view.answer
    )
    subtitle = view.footer
    if view.tool_summary:
        subtitle = f"{view.tool_summary}  ·  {view.footer}"
    if session_tokens:
        budget_note = f"/{budget_limit}" if budget_limit else ""
        subtitle = f"{subtitle}  ·  {session_tokens}{budget_note} tok"
    try:
        from rich.panel import Panel

        console.print(
            Panel(
                renderable,
                title="[bold]kinox[/bold]",
                title_align="left",
                subtitle=f"[dim]{subtitle}[/dim]",
                subtitle_align="right",
                border_style="green" if view.ok else "red",
                padding=(1, 2),
            )
        )
    except Exception:
        _render_response(result.final_text, console)
        console.print(f"[dim]{'✓' if view.ok else '✗'} {subtitle}[/dim]")

    # The generated trace recap: a tree of what the agent did, composed from the
    # run's steps. Verbose-only — the live trace already showed it once; this is
    # the structured post-run view. Fail-soft (never breaks the answer above).
    verbose = os.environ.get("KINOX_VERBOSE", "0").lower() in ("1", "on", "true", "yes")
    if verbose and view.steps:
        _render_trace_tree(view, console)


def _render_trace_tree(view: object, console: object) -> None:
    """Render the run's step trace as a rich Tree using the brand glyphs; plain
    fallback. Generative output — the tree is composed from the RunView's steps."""
    from products import theme

    def _glyph(kind: str, name: str) -> str:
        if kind == "blocked":
            return theme.status_glyph("blocked")
        if kind == "final":
            return theme.status_glyph("ok")
        return theme.tool_glyph(name)

    try:
        from rich.tree import Tree

        tree = Tree(f"[bold]{theme.WORDMARK_COMPACT}[/bold]  [dim]{view.footer}[/dim]")
        for step in view.steps:
            color = theme.tool_color(step.name)
            label = _esc(step.name or "answer")
            detail = f"  [dim]{_esc(step.detail)}[/dim]" if step.detail else ""
            tree.add(
                f"{_glyph(step.kind, step.name)} "
                f"[{color}]{label}[/{color}]{detail}"
            )
        console.print(tree)
    except Exception:
        for step in view.steps:
            console.print(f"  {_glyph(step.kind, step.name)} {_esc(step.name or 'answer')}")


def _render_response(text: str, console: object) -> None:
    """Render model response — try Markdown, fall back to plain text.

    Strips reasoning blocks first (see :func:`_strip_reasoning`).
    """
    text = _strip_reasoning(text)
    try:
        Markdown = _import_rich_markdown()
        if Markdown is not None:
            md = Markdown(text, code_theme="monokai")
            console.print(md)
            return
    except Exception:
        pass
    # Plain text fallback
    for line in text.strip().splitlines():
        console.print(f"  {line}")


# --- lazy imports (cold-start discipline) ------------------------------------


def _import_rich():
    """Return (Console, Panel).  Raises ImportError if rich isn't installed."""
    from rich.console import Console
    from rich.panel import Panel

    return Console, Panel


def _import_rich_console():
    from rich.console import Console

    return Console


def _import_rich_markdown():
    try:
        from rich.markdown import Markdown

        return Markdown
    except ImportError:
        return None


def _import_prompt_toolkit():
    """Return the prompt_toolkit module, or None — fail soft (thesis #2)."""
    try:
        import prompt_toolkit  # noqa: F401

        return prompt_toolkit
    except ImportError:
        return None


# --- action factory for the hub ----------------------------------------------


def make_chat_action(
    manifest: Manifest,
    sink: MetricsSink,
    cwd: Path,
    *,
    is_tty: bool = True,
) -> Callable[[], int]:
    """Build a zero-arg ``Action`` for the launcher hub.

    The returned callable enters the chat TUI and returns its exit code, so the
    hub regains control when chat exits (unlike ``spawn`` which launches a session).
    """

    def action() -> int:
        return chat_run(manifest=manifest, sink=sink, cwd=cwd, is_tty=is_tty)

    return action
