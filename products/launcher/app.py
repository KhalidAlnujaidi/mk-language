"""The launcher hub loop (design §"The seam").

The hub is the default working environment: it shows the menu, routes the
choice, and returns to the menu until you quit. Everything that touches the
terminal or spawns a process is injected — ``select`` (pick a row), ``spawn``
(launch claude in a scope), and the ``dashboard``/``doctor``/``new_project``
action handlers — so the routing here is pure control flow, unit-testable
without a real TTY. The real seams (questionary selection, rich header, the
``kin`` subprocess) are wired in G4-3/G4-4.

Contract mirror of ``kin``/``kx``: with no TTY on stdin the loop prints the menu
as a plan and exits 0 — it never blocks on ``select``.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

from products.launcher.menu import MenuItem, build_menu

#: Read one line of input (injectable so the text fallback is testable).
Prompt = Callable[[str], str]
#: Pick a row (or None to quit).
Selector = Callable[[list[MenuItem]], MenuItem | None]
#: Launch claude in the given scope dir (blocks until it exits).
Spawner = Callable[[Path], None]
#: A simple action (dashboard / doctor).
Action = Callable[[], None]
#: Prompt + scaffold a new project; return its dir to enter, or None to cancel.
NewProject = Callable[[], Path | None]
#: Draw the header + menu before selection.
Renderer = Callable[[list[MenuItem]], None]


def _print_plan(items: list[MenuItem]) -> None:
    """The non-interactive contract: print the menu rows and what each does."""
    print("==> kinox launcher · hub (non-interactive: printing the menu plan)")
    for item in items:
        target = f"  → {item.scope_dir}" if item.scope_dir is not None else ""
        print(f"    {item.label}{target}")


# --- selection seams (Rule Zero: reuse questionary; rich for the header) ------


def _import_questionary() -> Any | None:
    """Return the questionary module, or None if it isn't installed (SOFT)."""
    try:
        import questionary
    except ImportError:
        return None
    return questionary


def text_select(items: list[MenuItem], *, prompt: Prompt = input) -> MenuItem | None:
    """Numbered text-menu fallback when questionary is unavailable.

    Blank / non-numeric / out-of-range input cancels (returns None) rather than
    guessing — the loop treats None as "quit".
    """
    for n, item in enumerate(items, 1):
        print(f"  {n}. {item.label}")
    raw = prompt("select> ").strip()
    if not raw.isdigit():
        return None
    idx = int(raw)
    return items[idx - 1] if 1 <= idx <= len(items) else None


def _questionary_select(qmod: Any, items: list[MenuItem]) -> MenuItem | None:
    """Arrow-key selection via questionary, with a separator before the actions."""
    choices: list[Any] = []
    seen_action = False
    for item in items:
        # One separator line where the launchable scopes end and actions begin.
        if not seen_action and item.kind in ("new", "dashboard", "doctor", "quit"):
            choices.append(qmod.Separator())
            seen_action = True
        choices.append(qmod.Choice(title=item.label, value=item))
    answer: MenuItem | None = qmod.select(
        "kinox — pick a scope or action:",
        choices=choices,
        qmark="▸",
        pointer="▸",
    ).ask()
    return answer


def default_select(items: list[MenuItem], *, prompt: Prompt = input) -> MenuItem | None:
    """The real selector: questionary if present, else the numbered text menu."""
    qmod = _import_questionary()
    if qmod is None:
        return text_select(items, prompt=prompt)
    return _questionary_select(qmod, items)


def default_render(items: list[MenuItem]) -> None:
    """Draw the hub header. questionary draws the list, so this is just the banner."""
    try:
        from rich.console import Console
        from rich.panel import Panel
    except ImportError:
        print("kinox — local · governed · cost-efficient")
        return
    Console().print(
        Panel.fit(
            "[bold]kinox[/bold] · local · governed · cost-efficient",
            border_style="cyan",
        )
    )


def run(
    *,
    projects_dir: Path,
    spawn: Spawner,
    select: Selector | None = None,
    is_tty: bool = True,
    render: Renderer | None = None,
    dashboard: Action | None = None,
    doctor: Action | None = None,
    new_project: NewProject | None = None,
) -> int:
    """Run the hub loop until the user quits. Returns a process exit code.

    ``select``/``render`` default to the real questionary + rich seams; tests
    inject fakes. The no-TTY path returns before either is touched.
    """
    pick = select if select is not None else default_select
    draw = render if render is not None else default_render
    while True:
        items = build_menu(projects_dir)

        # No TTY (tests / pipes / CI): report the menu and leave — never block.
        if not is_tty:
            _print_plan(items)
            return 0

        draw(items)

        choice = pick(items)
        if choice is None or choice.kind == "quit":
            return 0

        kind = choice.kind
        if kind in ("admin", "project") and choice.scope_dir is not None:
            spawn(choice.scope_dir)
        elif kind == "new" and new_project is not None:
            scope = new_project()
            if scope is not None:
                spawn(scope)
        elif kind == "dashboard" and dashboard is not None:
            dashboard()
        elif kind == "doctor" and doctor is not None:
            doctor()
