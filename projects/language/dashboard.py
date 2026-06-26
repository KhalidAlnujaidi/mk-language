"""A zero-dependency LAN dashboard for the council experiment.

Pure stdlib http.server — never touches the run, only reads the files it writes,
so it cannot interfere. Auto-refreshes; shows the live status, the latest round's
proposals + ballots + Borda tally (de-anonymized), the growing spec, and the
tail of raw model reasoning from the dump.

Serve on the LAN:   .venv/bin/python projects/language/dashboard.py
Then open from any device on the Wi-Fi:   http://<this-machine-ip>:8800
"""

from __future__ import annotations

import html
import json
import re
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

HERE = Path(__file__).resolve().parent
PORT = 8800


def _read(path: Path, tail_bytes: int = 0) -> str:
    try:
        data = path.read_text(encoding="utf-8", errors="replace")
        return data[-tail_bytes:] if tail_bytes else data
    except OSError:
        return ""


def _latest_round() -> dict[str, object] | None:
    rounds = sorted((HERE / "rounds").glob("round-*.json"))
    if not rounds:
        return None
    try:
        return json.loads(rounds[-1].read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _esc(s: object) -> str:
    return html.escape(str(s))


def _sections(state: dict[str, object]) -> dict[str, dict[str, object]]:
    """Decided sections keyed by stage name (latest wins)."""
    out: dict[str, dict[str, object]] = {}
    for s in state.get("sections", []) or []:
        out[str(s.get("stage"))] = s
    return out


def _atoms(text: str) -> list[str]:
    """Pull the language's atoms/primitives — anything quoted or backticked —
    so the evolving syntax can be shown as a concrete grid, not prose."""
    toks = (
        re.findall(r"`([^`\n]{1,24})`", text)
        + re.findall(r'"([^"\n]{1,24})"', text)
        + re.findall(r"'([^'\n]{1,24})'", text)
    )
    seen: list[str] = []
    for t in toks:
        t = t.strip()
        if t and t not in seen:
            seen.append(t)
    return seen[:60]


def _first_line(sec: dict[str, object] | None) -> str:
    if not sec:
        return ""
    text = str(sec.get("text", ""))
    return text.splitlines()[0] if text else ""


def render() -> str:
    state = {}
    try:
        state = json.loads(_read(HERE / "state.json") or "{}")
    except json.JSONDecodeError:
        pass
    rnd = _latest_round()
    spec = _read(HERE / "SPEC.md")
    dump_tail = _read(HERE / "dump.log", tail_bytes=6000)
    caps: dict[str, object] = {}
    try:
        caps = json.loads(_read(HERE / "capabilities.json") or "{}")
    except json.JSONDecodeError:
        pass
    interp = _read(HERE / "interpreter.py")
    progress = _read(HERE / "PROGRESS.md")

    parts = [
        "<!doctype html><html><head><meta charset='utf-8'>",
        "<meta http-equiv='refresh' content='6'>",
        "<title>Council · language</title>",
        "<style>",
        "body{background:#0b0e14;color:#c8d3f5;font:14px/1.5 ui-monospace,monospace;",
        "margin:0;padding:24px;max-width:1100px;margin:auto}",
        "h1{color:#7aa2f7;font-size:20px}h2{color:#bb9af7;border-bottom:1px solid #2a2f3a;",
        "padding-bottom:4px;margin-top:28px}.pill{display:inline-block;background:#1f2430;",
        "border-radius:10px;padding:3px 10px;margin:2px 4px}.win{color:#9ece6a;font-weight:bold}",
        "pre{background:#11141c;border:1px solid #222733;border-radius:8px;padding:12px;",
        "white-space:pre-wrap;overflow-x:auto}.prop{border-left:3px solid #414868;",
        "padding:4px 10px;margin:8px 0;background:#11141c}.auth{color:#e0af68}",
        ".sc{color:#7dcfff}small{color:#565f89}",
        ".grid{display:flex;flex-wrap:wrap;gap:6px;margin:8px 0}",
        ".atom{background:#1a1f2e;border:1px solid #3b4261;border-radius:6px;",
        "padding:3px 9px;color:#9ece6a;font-weight:bold}",
        ".badge{display:inline-block;background:#2d2438;border:1px solid #6d4a9c;",
        "border-radius:8px;padding:4px 10px;margin:3px 5px;color:#e0c3ff}",
        "pre.lang{background:#0c1018;border-color:#2e3b2e;color:#b9e08a}",
        "h3{color:#73daca;margin:14px 0 4px}</style></head><body>",
        "<h1>🗳️  The Council — building a language by anonymous consensus</h1>",
    ]

    phase = _esc(state.get("phase", "?"))
    rd = _esc(state.get("round", "?"))
    nsec = len(state.get("sections", []) or [])
    parts.append(
        f"<div><span class='pill'>round <b>{rd}</b></span>"
        f"<span class='pill'>phase <b>{phase}</b></span>"
        f"<span class='pill'>{nsec} sections decided</span>"
        "<span class='pill'>qwen3 · gemma4 · llama3 · deepseek-r1 · mistral</span></div>"
    )

    # --- 🪜 Capability ladder — executed, not voted --------------------------
    if caps:
        allc = caps.get("all", []) or []
        passing = set(caps.get("passing", []) or [])
        score = _esc(caps.get("score", 0))
        total = _esc(caps.get("total", len(allc)))
        done = int(caps.get("score", 0) or 0) >= int(caps.get("total", 0) or 1)
        head = "✅ COMPLETE LANGUAGE" if done else "🪜 Building a real interpreter"
        parts.append(f"<h2>{head} — <span class='win'>{score}/{total}</span> "
                     "capabilities run</h2>")
        parts.append("<div class='grid'>")
        for name in allc:
            ok = name in passing
            color = "#9ece6a" if ok else "#565f89"
            mark = "✅" if ok else "⬜"
            parts.append(
                f"<span class='atom' style='color:{color};border-color:{color}'>"
                f"{mark} {_esc(name)}</span>"
            )
        parts.append("</div>")
        if interp:
            parts.append("<h3>the interpreter the council wrote "
                         "<small>· interpreter.py</small></h3>")
            parts.append(f"<pre class='lang'>{_esc(interp[:5000])}</pre>")
        if progress:
            parts.append("<h3>anonymized progress reference "
                         "<small>· PROGRESS.md (institutional memory)</small></h3>")
            parts.append(f"<pre>{_esc(progress[-3000:])}</pre>")

    # --- 🧬 The Language so far — concrete artifacts, not prose ---------------
    secs = _sections(state)
    if secs:
        parts.append("<h2>🧬 The Language they are building</h2>")
        badges = []
        for stage, label in (("notation", "notation"), ("paradigm-and-types", "paradigm")):
            fl = _first_line(secs.get(stage))
            if fl:
                badges.append(f"<span class='badge'>{label}: <b>{_esc(fl[:54])}</b></span>")
        if badges:
            parts.append("<div>" + "".join(badges) + "</div>")

        atom_src = (
            str((secs.get("lexical-grammar") or {}).get("text", ""))
            + "\n"
            + str((secs.get("builtins") or {}).get("text", ""))
            + "\n"
            + str((secs.get("core-grammar") or {}).get("text", ""))
        )
        atoms = _atoms(atom_src)
        if atoms:
            parts.append("<h3>atoms &amp; primitives</h3><div class='grid'>")
            parts += [f"<span class='atom'>{_esc(a)}</span>" for a in atoms]
            parts.append("</div>")

        for stage, label in (("core-grammar", "grammar (EBNF)"), ("semantics", "semantics")):
            s = secs.get(stage)
            if s:
                parts.append(
                    f"<h3>{label} <small>· {_esc(s.get('author'))}</small></h3>"
                    f"<pre class='lang'>{_esc(str(s.get('text', ''))[:2600])}</pre>"
                )

        examples = [v for k, v in secs.items() if k.startswith("example")]
        if examples:
            parts.append("<h3>how it looks — example programs</h3>")
            for s in examples:
                parts.append(
                    f"<small>{_esc(s.get('stage'))} · {_esc(s.get('author'))}</small>"
                    f"<pre class='lang'>{_esc(str(s.get('text', ''))[:1800])}</pre>"
                )

    if rnd:
        parts.append(f"<h2>Latest round {_esc(rnd.get('index'))} — {_esc(rnd.get('title'))}</h2>")
        scores = rnd.get("scores", {}) or {}
        wauthor = _esc(rnd.get("winner_author"))
        note = _esc(rnd.get("note") or "")
        parts.append(f"<p>winner: <span class='win'>{wauthor}</span> {note} "
                     f"<span class='sc'>scores {_esc(scores)}</span></p>")
        for opt in rnd.get("options", []) or []:
            lab = _esc(opt.get("label"))
            auth = _esc(opt.get("author"))
            sc = _esc(scores.get(opt.get("label"), ""))
            text = _esc((opt.get("text") or "")[:1400])
            parts.append(
                f"<div class='prop'><b>{lab}</b> <span class='auth'>[{auth}]</span> "
                f"<span class='sc'>borda {sc}</span><br><small>{text}</small></div>"
            )
        ballots = rnd.get("ballots", {}) or {}
        parts.append("<p><small>ballots (blind): "
                     + _esc(ballots) + "</small></p>")

    parts.append("<h2>Live spec</h2><pre>" + _esc(spec) + "</pre>")
    parts.append("<h2>Raw reasoning (dump tail)</h2><pre>" + _esc(dump_tail) + "</pre>")
    parts.append("<p><small>auto-refresh 6s · read-only · does not touch the run</small></p>")
    parts.append("</body></html>")
    return "".join(parts)


class Handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802
        body = render().encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *_args: object) -> None:
        pass  # quiet


if __name__ == "__main__":
    srv = ThreadingHTTPServer(("0.0.0.0", PORT), Handler)
    print(f"dashboard on http://0.0.0.0:{PORT}", flush=True)
    srv.serve_forever()
