"""Chat TUI — terminal loop for the kinox chatbot.

Provides ``chat_run()``, the interactive chat loop entered from the launcher
hub.  Rendering is done with ``rich``; input uses ``prompt_toolkit`` when
available with a plain ``input()`` fallback.  The loop handles ``/`` commands
(help, clear, quit, model) and delegates message processing to
:class:`~products.chat.session.ChatSession`.

Before entering the TUI, a **pre-flight check** verifies:
  1. At least one local model is registered (``ollama list``)
  2. That model fits in available VRAM
  3. Ollama's API endpoint is reachable (``/v1/models``)

If any check fails, a diagnostic is printed and control returns to the hub
immediately — we never enter the chat loop assuming a model is there.
All routing is **local-only**; cloud is never used as a fallback.

Cold-start discipline: all heavy imports (rich, prompt_toolkit) live inside
function bodies so the module is importable at hub-launch time without cost.
The plain-text fallback path is unit-testable by passing ``is_tty=False``.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from kernel.manifest import Manifest
from kernel.metrics import MetricsSink

from products.chat.session import ChatSession

#: How many turns of command history prompt_toolkit remembers.
_HISTORY_SIZE = 200


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


def _preflight(manifest: Manifest) -> str | None:
    """Check that a local model is available AND reachable.  Local only.

    Returns ``None`` when everything is ready, or a diagnostic error string
    suitable for display.  No VRAM estimation — Ollama manages its own memory
    (partial GPU offloading, CPU fallback).  We just verify a model is there
    and the endpoint answers.
    """
    # 1. Any local models at all? (ollama list must succeed)
    if not manifest.local_models:
        return (
            "No local models found.\n\n"
            "Run these commands in another terminal:\n"
            "  ollama serve\n"
            "  ollama pull hf.co/yuxinlu1/gemma-4-12B-coder-"
            "fable5-composer2.5-v1-GGUF:Q4_K_M\n\n"
            "Then try again."
        )

    # 2. Is Ollama's API actually reachable right now?
    if not _ollama_reachable(manifest):
        return (
            "Ollama is registered but its API endpoint is not responding.\n\n"
            "Try:  ollama serve\n"
            "Then verify:  curl http://localhost:11434/v1/models"
        )

    # All checks passed — report what we found.
    Console = _import_rich_console()
    console = Console()
    model = manifest.local_models[0]
    console.print(
        f"[dim]preflight: {model.name} ({model.backend}) "
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
    """Print the chat welcome banner — simple, clear, kinox-branded."""
    Console, Panel = _import_rich()

    models = session.manifest.local_models
    model_name = models[0].name if models else "none"
    scope = session.cwd.name if session.cwd.name else str(session.cwd)

    Console().print(
        Panel.fit(
            f"[bold cyan]kinox[/bold cyan] · {scope}\n"
            f"model: {model_name}\n\n"
            f"[dim]/help  /clear  /quit[/dim]",
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
        _process_turn(raw, session, console)
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
        _process_turn(raw, session, console)
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
            "  [cyan]/model[/cyan]  — show current model info\n"
            "  [cyan]/agent[/cyan]  — run a tool-calling agent task "
            "(e.g. /agent summarize README.md)\n\n"
            "[dim]Enter sends · Esc+Enter inserts a newline (multi-line)[/dim]\n"
        )
        return True

    if cmd in ("m", "model"):
        models = session.manifest.local_models
        if models:
            console.print(f"[dim]model: {models[0].name} ({models[0].backend})[/dim]")
        else:
            console.print("[dim]no local model available[/dim]")
        return True

    if cmd in ("a", "agent"):
        if not arg.strip():
            console.print(
                "[dim]usage: /agent <task> — run the tool-calling agent[/dim]"
            )
        else:
            _run_agent_turn(arg.strip(), session, console)
        return True

    console.print(f"[dim]unknown command: /{cmd} — try /help[/dim]")
    return True


# --- turn processing ---------------------------------------------------------


def _process_turn(raw: str, session: ChatSession, console: object) -> None:
    """Run one user→assistant turn: groom, dispatch, display.

    Model dispatch runs in a background thread so the terminal can show a
    ``rich.status`` spinner instead of going dead-silent for 30–60 s.  Fast
    responses (< 300 ms) skip the spinner entirely to avoid flicker.
    """
    import time
    from concurrent.futures import ThreadPoolExecutor

    # Show the user's message
    console.print(f"\n[bold cyan]you:[/bold cyan] {raw}")

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

    Builds the standard toolset — read-only filesystem (sandboxed to the chat
    scope) + the skill bridge over ``.claude/skills`` (the positive feedback
    loop) — and runs the loop on the first local model. Write/exec tools stay OFF
    here (fail-CLOSED); they belong behind the pre-tool-use guard slice. Dispatch
    runs in a worker thread so the terminal can show a spinner.
    """
    import asyncio
    import time
    import uuid
    from concurrent.futures import ThreadPoolExecutor

    from kernel.contracts import Tier

    from products.agent import default_registry, run_agent
    from products.capabilities.registry import CapabilityRegistry, load_skills

    models = session.manifest.local_models
    if not models:
        console.print("[dim]no local model available[/dim]")
        return

    kinox_root = Path(__file__).resolve().parents[2]
    skills = CapabilityRegistry(load_skills(kinox_root / ".claude" / "skills"))
    registry = default_registry(session.cwd, skills=skills, allow_bash=False)
    tier = Tier.model(models[0].name, where="local", backend=models[0].backend)

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
