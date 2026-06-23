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

from products.launcher.menu import MenuItem, build_menu

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


def run(
    *,
    projects_dir: Path,
    select: Selector,
    spawn: Spawner,
    is_tty: bool = True,
    render: Renderer | None = None,
    dashboard: Action | None = None,
    doctor: Action | None = None,
    new_project: NewProject | None = None,
) -> int:
    """Run the hub loop until the user quits. Returns a process exit code."""
    while True:
        items = build_menu(projects_dir)

        # No TTY (tests / pipes / CI): report the menu and leave — never block.
        if not is_tty:
            _print_plan(items)
            return 0

        if render is not None:
            render(items)

        choice = select(items)
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
