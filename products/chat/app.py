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

from products.chat.session import ChatSession

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

    session = ChatSession(
        manifest=manifest,
        sink=sink,
        cwd=cwd,
        system_prompt=system_prompt or ChatSession.system_prompt,
    )

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

    Console().print(
        Panel.fit(
            f"[bold cyan]kinox[/bold cyan] · {scope}\n"
            f"{model_block}\n"
            f"[dim]agent mode · read · write · bash · skills[/dim]\n\n"
            f"[dim]/help  /model  /chat  /quit[/dim]",
            border_style="cyan",
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
    from prompt_toolkit.history import InMemoryHistory
    from prompt_toolkit.key_binding import KeyBindings
    from prompt_toolkit.styles import Style

    history = InMemoryHistory()

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

    style = Style.from_dict(
        {
            "prompt": "ansicyan bold",
            "bottom-toolbar": "dim",
        }
    )

    def bottom_toolbar() -> str:
        n = len(session.history) // 2
        return (
            f" turns: {n}  |  Enter to send · Esc+Enter newline  "
            "|  /help /clear /quit"
        )

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
            "  [cyan]/agent[/cyan]  — explicit agent task (turns are agent mode)\n\n"
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

    if cmd == "chat":
        # Escape hatch: one plain, tool-less reply (cheap conversation).
        if not arg.strip():
            console.print("[dim]usage: /chat <message> — a plain reply, no tools[/dim]")
        else:
            _process_turn(arg.strip(), session, console)
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


def _run_agent_turn(task: str, session: ChatSession, console: object) -> None:
    """Run one tool-calling agent task and render its step trace + answer.

    This is the **default** turn for a ``kx`` session: the full, unrestricted
    toolset — read + ``write_file`` + ``run_bash`` + the skill bridge over
    ``.claude/skills`` (275 skills) — sandboxed to the session scope, with NO
    pre-tool guard. The session is fully trusted (it is the operator's own admin
    shell), so write/exec are ON. Dispatch runs in a worker thread for the
    spinner.
    """
    import asyncio
    import time
    import uuid
    from concurrent.futures import ThreadPoolExecutor

    from daemon.brain import brain_tier
    from kernel.contracts import Tier

    from products.agent import default_registry, run_agent
    from products.capabilities.registry import CapabilityRegistry

    kinox_root = Path(__file__).resolve().parents[2]
    # The FULL harvested corpus: skills + commands + agent playbooks + MCP
    # descriptors — all discoverable via find_skill/load_skill.
    skills = CapabilityRegistry.from_claude_dir(kinox_root / ".claude")
    # Unrestricted: write + bash ON, no guard — a fully-trusted operator agent.
    # MCP servers in .claude/mcp-servers.json are started and exposed as live
    # tools (fail-soft). Gated by KINOX_MCP (default on) because the first turn
    # pays the server cold-start; set KINOX_MCP=0 to skip. Cached after start.
    mcp_on = os.environ.get("KINOX_MCP", "1").lower() not in ("0", "off", "false", "no")
    mcp_config = kinox_root / ".claude" / "mcp-servers.json" if mcp_on else None
    if mcp_config is not None and str(mcp_config) not in _mcp_started:
        console.print("[dim]connecting MCP servers (set KINOX_MCP=0 to skip)…[/dim]")
        _mcp_started.add(str(mcp_config))
    registry = default_registry(
        session.cwd,
        skills=skills,
        allow_bash=True,
        allow_write=True,
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
    tier = brain_tier(fallback=local_tier)
    if tier is None:
        console.print(
            "[dim]no model available (set ZAI_API_KEY or run a local model)[/dim]"
        )
        return

    console.print(f"\n[bold cyan]agent:[/bold cyan] {task}")
    console.print(
        f"[dim]tools: {', '.join(registry.tools)}  ·  skills: {len(skills)}[/dim]"
    )

    def work() -> object:
        return asyncio.run(
            run_agent(
                task,
                tier=tier,
                registry=registry,
                sink=session.sink,
                task_id=uuid.uuid4().hex[:12],
                fallback=local_tier,
                max_turns=30,  # real dev tasks need room to read → act → verify
            )
        )

    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(work)
        start = time.monotonic()
        with console.status("[dim]agent working…[/dim]", spinner="dots") as status:
            while not future.done():
                status.update(
                    f"[dim]agent working… ({time.monotonic() - start:.1f}s)[/dim]"
                )
                time.sleep(0.25)
        try:
            result = future.result()
        except Exception as exc:  # noqa: BLE001 — surface, never crash the TUI
            console.print(f"[bold red]agent error:[/bold red] {exc}")
            return

    # Step trace: each tool call / block, then the final answer.
    for step in result.steps:
        if step.kind == "tool":
            console.print(f"  [yellow]→ {step.name}[/yellow] [dim]{step.detail}[/dim]")
        elif step.kind == "blocked":
            console.print(f"  [red]⛔ {step.name} blocked: {step.detail}[/red]")
    label = f" ({result.stopped}, {result.turns} turns)"
    console.print(f"[bold green]kinox agent{label}:[/bold green]")
    _render_response(result.final_text, console)
    console.print()


def _render_response(text: str, console: object) -> None:
    """Render model response — try Markdown, fall back to plain text."""
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
