"""products/theme.py — the kinox visual identity (one source of truth).

Pure data + string helpers. **No rich import at module load** (cold-start
discipline + trivially testable): callers own the ``Console``; this module just
returns rich-markup strings, the ASCII wordmark, the tool icon/colour maps, and
the ``bar``/``spark`` unicode helpers used across the launcher, chat, and
dashboard surfaces.

Every glyph degrades to plain ASCII when ``KINOX_ASCII`` is set (or ``NO_COLOR``
for the gradient) so the TUI stays legible on dumb terminals and in pipes. The
wordmark is hand-drawn ANSI-shadow block letters — no figlet dependency, in
keeping with the dependency-light outer layer.
"""

from __future__ import annotations

import os

# --- brand palette -----------------------------------------------------------

#: Primary brand hue (matches the historical cyan border used everywhere).
PRIMARY = "cyan"
#: Accent for highlights / active states.
ACCENT = "bright_cyan"
#: Border style for framed panels.
BORDER = "cyan"
#: Box name resolved lazily by :func:`box` (rich.box attribute name).
BOX = "ROUNDED"
#: One-line brand promise shown under the wordmark.
TAGLINE = "local · governed · cost-efficient"

#: Cyan→indigo vertical gradient applied per wordmark row.
GRADIENT = ["#34ffe0", "#22e6e6", "#19c8f0", "#2f9bff", "#4a7bff", "#6a5cff"]

#: Hand-drawn ANSI-shadow wordmark (6 rows, aligns to GRADIENT).
WORDMARK = [
    " ██╗  ██╗ ██╗ ███╗   ██╗  ██████╗  ██╗  ██╗",
    " ██║ ██╔╝ ██║ ████╗  ██║ ██╔═══██╗ ╚██╗██╔╝",
    " █████╔╝  ██║ ██╔██╗ ██║ ██║   ██║  ╚███╔╝",
    " ██╔═██╗  ██║ ██║╚██╗██║ ██║   ██║  ██╔██╗",
    " ██║  ██╗ ██║ ██║ ╚████║ ╚██████╔╝ ██╔╝ ██╗",
    " ╚═╝  ╚═╝ ╚═╝ ╚═╝  ╚═══╝  ╚═════╝  ╚═╝  ╚═╝",
]
#: One-line wordmark for narrow terminals / the ASCII fallback.
WORDMARK_COMPACT = "▟▛ kinox ▜▙"

# --- tool trace styling ------------------------------------------------------

#: Tool name → accent colour for the live trace. ``mcp__*`` falls back to blue.
TOOL_COLORS = {
    "read_file": "cyan",
    "list_dir": "cyan",
    "find_skill": "green",
    "load_skill": "green",
    "write_file": "yellow",
    "run_bash": "magenta",
}
#: Tool name → glyph for the live trace (emoji; → fallback under KINOX_ASCII).
TOOL_GLYPHS = {
    "read_file": "📖",
    "list_dir": "📂",
    "find_skill": "🔍",
    "load_skill": "🔧",
    "write_file": "✏️ ",
    "run_bash": "⚡",
}

#: Status glyphs (ok / blocked / fail), with ASCII fallbacks below.
OK = "✓"
BLOCKED = "⛔"
FAIL = "✗"
BRAIN = "🧠"
CLOUD = "☁"


#: Bite-sized usage hints rotated through the toolbar / welcome / dashboard.
#: Keep each short enough to live on one toolbar line (~60 cols).
TIPS = [
    "/model switches the brain mid-session",
    "Esc+Enter inserts a newline · Enter sends",
    "Ctrl+U clears the whole input · Ctrl+W deletes a word",
    "/chat resets the conversation context",
    "KINOX_VERBOSE=1 shows the full tool trace",
    "kx doctor runs a health check",
    "kx status opens the observability dashboard",
    "/help lists every command",
    "Shift-Tab inserts a tab in the prompt",
    "KINOX_ASCII=1 forces a glyph-free render",
    "KINOX_MCP=0 skips the MCP server cold-start",
]


def tip(n: int = 0) -> str:
    """The ``n``-th hint (wraps around), prefixed with 💡 unless ASCII-only.

    Callers pass a rotating index — turn count, pid, or event total — so the
    hint changes over time without any stored state.
    """
    if not TIPS:
        return ""
    bulb = "" if ascii_only() else "💡 "
    return f"{bulb}{TIPS[n % len(TIPS)]}"


def ascii_only() -> bool:
    """True when the user asked for a glyph-free render (dumb terminals/pipes)."""
    return os.environ.get("KINOX_ASCII", "").lower() in ("1", "on", "true", "yes")


def no_color() -> bool:
    """Honour the NO_COLOR convention for the gradient (https://no-color.org)."""
    return bool(os.environ.get("NO_COLOR")) or ascii_only()


# --- renderable string builders ----------------------------------------------


def wordmark(*, gradient: bool = True, width: int | None = None) -> str:
    """Return the wordmark as a rich-markup string.

    Falls back to the compact one-liner under ``KINOX_ASCII`` or when ``width``
    is too small for the full block letters (they need ~44 cols).
    """
    if ascii_only() or (width is not None and width < 46):
        return f"[bold {PRIMARY}]{WORDMARK_COMPACT}[/]"
    if no_color() or not gradient:
        return "\n".join(f"[bold {PRIMARY}]{line}[/]" for line in WORDMARK)
    rows: list[str] = []
    for i, line in enumerate(WORDMARK):
        rows.append(f"[{GRADIENT[i % len(GRADIENT)]}]{line}[/]")
    return "\n".join(rows)


def banner_text(subtitle: str = TAGLINE, *, width: int | None = None) -> str:
    """Wordmark + a dim subtitle, as one markup blob (no Panel)."""
    return f"{wordmark(width=width)}\n[dim]{subtitle}[/dim]"


def tool_glyph(name: str) -> str:
    """Glyph for a tool name (→ for unknowns; arrow-only under KINOX_ASCII)."""
    if ascii_only():
        return "→"
    if name.startswith("mcp__"):
        return "🔌"
    return TOOL_GLYPHS.get(name, "→")


def tool_color(name: str) -> str:
    """Accent colour for a tool name (mcp__* → blue, else yellow default)."""
    return TOOL_COLORS.get(name, "blue" if name.startswith("mcp__") else "yellow")


def status_glyph(kind: str) -> str:
    """ok/blocked/fail glyph with ASCII fallback."""
    if ascii_only():
        return {"ok": "[OK]", "blocked": "[X]", "fail": "[!]"}.get(kind, "")
    return {"ok": OK, "blocked": BLOCKED, "fail": FAIL}.get(kind, "")


def box():
    """Resolve the brand box style (lazy rich import; ASCII box as fallback)."""
    from rich import box as _box

    return getattr(_box, "ASCII" if ascii_only() else BOX, _box.ROUNDED)


# --- mini data viz (pure unicode, no deps) -----------------------------------

_BAR_FRAC = " ▏▎▍▌▋▊▉█"  # eighth-block fractions for sub-cell precision
_SPARK = "▁▂▃▄▅▆▇█"


def bar(value: float | int | None, vmax: float | int | None, width: int = 10) -> str:
    """Proportional horizontal bar scaled to ``vmax`` (sub-cell precise).

    Returns a dot-padded ``width``-cell string. ``None``/zero-max → all dots, so
    an unknown metric reads as empty rather than a fake full bar.
    """
    pad = "·" if not ascii_only() else "."
    if not vmax or value is None or value <= 0:
        return pad * width
    frac = max(0.0, min(1.0, value / vmax)) * width
    n = int(frac)
    if ascii_only():
        return ("#" * min(width, n + (1 if frac - n >= 0.5 else 0))).ljust(width, ".")
    s = "█" * n
    if n < width:
        s += _BAR_FRAC[int((frac - n) * 8)]
    return s.ljust(width, pad)


def spark(values: list[float | int | None], width: int | None = None) -> str:
    """Unicode sparkline for a sequence. Empty/zero → flat baseline.

    ``None`` entries (gaps in a series) are dropped before scaling.
    """
    vals = [v for v in values if v is not None]
    if not vals:
        return ""
    if width is not None and len(vals) > width:  # downsample to width buckets
        step = len(vals) / width
        vals = [vals[int(i * step)] for i in range(width)]
    lo, hi = min(vals), max(vals)
    if hi == lo:
        return ("─" if not ascii_only() else "-") * len(vals)
    if ascii_only():
        ramp = ".:-=+*#@"
        return "".join(ramp[min(7, int((v - lo) / (hi - lo) * 7))] for v in vals)
    return "".join(_SPARK[min(7, int((v - lo) / (hi - lo) * 7))] for v in vals)
