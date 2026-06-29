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
import socket
import time
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


def _fmt_ago(sec: float) -> str:
    sec = int(sec)
    if sec < 90:
        return f"{sec}s ago"
    if sec < 5400:
        return f"{sec // 60}m ago"
    return f"{sec // 3600}h {(sec % 3600) // 60}m ago"


def _heartbeat() -> tuple[str, str, str]:
    """(state_word, color, ago_text) from the freshest run file.

    The HTTP server can answer long after the council loop has died, so the
    only honest liveness signal is whether the files the loop writes are still
    changing. Use the newest mtime among the state, the live reasoning dump,
    and the latest round.
    """
    candidates = [HERE / "state.json", HERE / "dump.log"]
    rounds = sorted((HERE / "rounds").glob("round-*.json"))
    if rounds:
        candidates.append(rounds[-1])
    newest = 0.0
    for p in candidates:
        try:
            newest = max(newest, p.stat().st_mtime)
        except OSError:
            pass
    if not newest:
        return "no run files", "#565f89", "—"
    age = max(0.0, time.time() - newest)
    if age < 300:
        return "live", "#9ece6a", _fmt_ago(age)
    if age < 1800:
        return "idle", "#e0af68", _fmt_ago(age)
    return "stalled", "#f7768e", _fmt_ago(age)


def _sections(state: dict[str, object]) -> dict[str, dict[str, object]]:
    """Decided sections keyed by stage name (latest wins)."""
    out: dict[str, dict[str, object]] = {}
    for s in state.get("sections", []) or []:
        out[str(s.get("stage"))] = s
    return out


def _active_models() -> list[str]:
    """The models actually on the council right now — read from the freshest round
    log's proposal authors (always current, and it survives a backend swap with no
    change here). Falls back to the last RUN START roster line in the dump."""
    rnd = _latest_round()
    if rnd:
        authors: list[str] = []
        for opt in rnd.get("options", []) or []:
            a = str(opt.get("author") or "").strip()
            if a and a not in authors:
                authors.append(a)
        if authors:
            return authors
    found = re.findall(r"roster=\(([^)]*)\)", _read(HERE / "dump.log", tail_bytes=300000))
    if found:
        return [s.strip().strip("'\"") for s in found[-1].split(",") if s.strip()]
    return []


def _backend_label(models: list[str]) -> tuple[str, str]:
    """(label, color): cloud frontier via OpenRouter vs local Ollama, inferred from
    the model-id shape (``provider/model`` ⇒ OpenRouter)."""
    if any("/" in m for m in models):
        return "OpenRouter · cloud frontier", "#7dcfff"
    if models:
        return "local · Ollama", "#9ece6a"
    return "—", "#565f89"


def _round_times() -> dict[str, dict[str, int]]:
    """Per-round wall times from run.out, split by backend. The cutover is the first
    round whose winning author is a provider/model slug (contains '/') — every round at
    or after it is 'cloud' (OpenRouter), earlier ones 'local' (Ollama). Counting by
    round INDEX (not by whether a winner was named) keeps forfeit rounds in the average,
    so the per-round time is honest rather than survivor-biased toward fast wins."""
    out = _read(HERE / "run.out")
    named = [(int(r), a) for r, a, _s in
             re.findall(r"round (\d+) done: \S+ -> (\S+) \((\d+)s\)", out)]
    cloud_idx = [r for r, a in named if "/" in a]
    cutover = min(cloud_idx) if cloud_idx else None
    local, cloud = [], []
    for r, s in re.findall(r"round (\d+) done:.*?\((\d+)s\)", out):
        (cloud if cutover is not None and int(r) >= cutover else local).append(int(s))

    def stat(xs: list[int]) -> dict[str, int]:
        return {"n": len(xs), "avg": (sum(xs) // len(xs)) if xs else 0,
                "min": min(xs) if xs else 0, "max": max(xs) if xs else 0}
    return {"local": stat(local), "cloud": stat(cloud)}


def _milestones() -> list[tuple[str, str]]:
    """(round, text) milestones from the anonymized PROGRESS.md institutional memory."""
    out: list[tuple[str, str]] = []
    for line in _read(HERE / "PROGRESS.md").splitlines():
        m = re.match(r"- Round (\d+): (.*)", line.strip())
        if m:
            out.append((m.group(1), re.sub(r"\*\*|`", "", m.group(2))))
    return out


def _alignment(rnd: dict[str, object] | None, total: int) -> dict[str, object]:
    """From the latest round: who converged and who didn't. In a build round the score
    is the #capabilities each model's interpreter passed; the max is the frontier."""
    if not rnd:
        return {}
    scores = {k: int(v) for k, v in (rnd.get("scores", {}) or {}).items()}
    if not scores:
        return {}
    top = max(scores.values())
    return {
        "top": top,
        "aligned": [k for k, v in scores.items() if v == top and top > 0],
        "partial": [k for k, v in scores.items() if 0 < v < top],
        "forfeit": [k for k, v in scores.items() if v == 0],
        "winner": rnd.get("winner_author"), "note": rnd.get("note"),
        "title": rnd.get("title"), "scores": scores,
    }


def _versions() -> dict[str, object]:
    """The version timeline (what each version did / is doing) + which is current."""
    try:
        return json.loads(_read(HERE / "versions.json") or "{}")
    except json.JSONDecodeError:
        return {}


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



def _sql_findings_html() -> str:
    """Render the MK↔SQL (context-computing) experiment results panel."""
    return """
<h2 style='color:#e0af68;border-color:#4a3a1e'>🔬 MK × SQL — Principle of Least Generation on WikiSQL</h2>
<div style='background:#11141c;border:1px solid #2a2f3a;border-radius:10px;padding:14px 16px'>

  <div style='display:flex;flex-wrap:wrap;gap:10px;margin:0 0 10px'>
    <span class='pill' style='border:1px solid #9ece6a'>80,654 queries</span>
    <span class='pill' style='border:1px solid #7dcfff'>488 templates</span>
    <span class='pill' style='border:1px solid #bb9af7'>0 generated tokens (assembly)</span>
    <span class='pill' style='border:1px solid #e0af68'>code: mk_sql.py · mk_sql_cgate.py</span>
  </div>

  <!-- Stage 1 -->
  <div style='background:#0d1119;border:1px solid #2e3b2e;border-radius:8px;padding:10px 12px;margin:8px 0'>
    <div style='color:#9ece6a;font-weight:bold'>✅ Stage 1 — Template Mining (structure is retrievable)</div>
    <div style='margin:4px 0'>80,654 queries collapse to <b>488 distinct structural templates</b> (agg × condition-ops).</div>
    <div><b>1 template covers 53.1%</b> · 9 cover 80% · 28 cover 90% · 62 cover 95% · 183 cover 99%</div>
    <div style='color:#9ece6a;margin-top:4px'>Verdict: SQL shape is near-zero-entropy. Generation = routing over a handful of patterns. PLG confirmed.</div>
  </div>

  <!-- Stage 2 -->
  <div style='background:#0d1119;border:1px solid #3b3826;border-radius:8px;padding:10px 12px;margin:8px 0'>
    <div style='color:#e0af68;font-weight:bold'>⚠️ Stage 2 — Zero-Gen Slot-Filler (grounding is the ceiling)</div>
    <div style='margin:4px 0'>Naive deterministic filler (lexical matching): <b>42.5% exact-match</b> (always-answer).</div>
    <div style='color:#e0af68;margin-top:4px'>Structure is free; value-grounding is the hard part: which column? which cell value?</div>
  </div>

  <!-- Stage 3 -->
  <div style='background:#0d1119;border:1px solid #3b3826;border-radius:8px;padding:10px 12px;margin:8px 0'>
    <div style='color:#e0af68;font-weight:bold'>⚠️ Stage 3 — The Gate (confidence sweep)</div>
    <div style='margin:4px 0'>Route top-confidence X% at 0 tokens; escalate the rest:</div>
    <table style='border-collapse:collapse;margin:6px 0;font-size:13px'>
      <tr style='color:#7dcfff'><th style='padding:2px 12px;text-align:left'>coverage</th><th style='padding:2px 12px'>precision @ 0 tokens</th></tr>
      <tr><td style='padding:2px 12px'>10%</td><td style='padding:2px 12px;color:#e0af68'>67.2%</td></tr>
      <tr style='background:#16201a'><td style='padding:2px 12px'>25%</td><td style='padding:2px 12px;color:#9ece6a'><b>72.1% (peak)</b></td></tr>
      <tr><td style='padding:2px 12px'>50%</td><td style='padding:2px 12px;color:#e0af68'>61.2%</td></tr>
      <tr><td style='padding:2px 12px'>100%</td><td style='padding:2px 12px;color:#f7768e'>42.4%</td></tr>
    </table>
    <div style='color:#e0af68;margin-top:4px'>Gate idea is sound (72% vs 42% baseline) — but lexical features are a weak predictor. Clean PLG gate (80% @ ≥95%) not reachable with token overlap.</div>
  </div>

  <!-- Stage 4 -->
  <div style='background:#0d1119;border:1px solid #3b2626;border-radius:8px;padding:10px 12px;margin:8px 0'>
    <div style='color:#f7768e;font-weight:bold'>❌ Stage 4 — c_gate Substitution (MK ↔ context-computing) — NEGATIVE</div>
    <div style='margin:4px 0'>Hypothesis: replace lexical SELECT-column choice with embedding similarity (Ollama nomic-embed-text).</div>
    <table style='border-collapse:collapse;margin:6px 0;font-size:13px'>
      <tr style='color:#7dcfff'><th style='padding:2px 12px;text-align:left'>variant</th><th style='padding:2px 12px'>exact-match</th><th style='padding:2px 12px'>vs lexical</th></tr>
      <tr style='background:#16201a'><td style='padding:2px 12px'>lexical (baseline)</td><td style='padding:2px 12px;color:#9ece6a'>41.3%</td><td style='padding:2px 12px'>—</td></tr>
      <tr><td style='padding:2px 12px'>c_gate, whole question</td><td style='padding:2px 12px;color:#f7768e'>25.3%</td><td style='padding:2px 12px;color:#f7768e'><b>−16.0</b></td></tr>
      <tr><td style='padding:2px 12px'>c_gate, residual</td><td style='padding:2px 12px;color:#f7768e'>26.7%</td><td style='padding:2px 12px;color:#f7768e'><b>−14.7</b></td></tr>
      <tr><td style='padding:2px 12px'>hybrid (lexical + c_gate fallback)</td><td style='padding:2px 12px;color:#e0af68'>34.7%</td><td style='padding:2px 12px;color:#f7768e'><b>−6.7</b></td></tr>
    </table>
    <div style='color:#f7768e;margin-top:4px'>Off-the-shelf dense cosine is worse than lexical. WikiSQL questions echo column names literally — generic embeddings add noise. The real c_gate needs schema-aware reps or the learned low-rank operator.</div>
  </div>

  <!-- Conclusion -->
  <div style='background:#0d1119;border:1px solid #2e4a5a;border-radius:8px;padding:10px 12px;margin:8px 0'>
    <div style='color:#7dcfff;font-weight:bold;margin-bottom:4px'>📋 Where the bits actually are</div>
    <div style='margin:2px 0'><b style='color:#9ece6a'>Structure:</b> retrievable (Stage 1). The skeleton needs no generation.</div>
    <div style='margin:2px 0'><b style='color:#e0af68'>Grounding:</b> semantic (Stage 2/3). Column/value identification is a similarity problem.</div>
    <div style='margin:2px 0'><b style='color:#f7768e'>Naive embeddings:</b> do NOT beat lexical (Stage 4). Need schema-aware reps or learned low-rank operator.</div>
  </div>

</div>
"""


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

    # --- status bar: is it running, and on what ------------------------------
    word, color, ago = _heartbeat()
    dot = "●" if word in ("live", "idle") else ("○" if word == "no run files" else "◍")
    host = _esc(socket.gethostname())
    parts.append(
        "<div style='margin:6px 0 2px'>"
        f"<span class='pill' style='border:1px solid {color}'>"
        f"<b style='color:{color}'>{dot} {word}</b></span>"
        f"<span class='pill'>updated <b>{_esc(ago)}</b></span>"
        f"<span class='pill'>host <b>{host}</b></span>"
        "<span class='pill'>:8800 · refresh 6s</span></div>"
    )

    phase = _esc(state.get("phase", "?"))
    rd = _esc(state.get("round", "?"))
    goal = _esc(state.get("goal", "?"))
    nsec = len(state.get("sections", []) or [])
    models = _active_models()
    blabel, bcolor = _backend_label(models)
    models_str = _esc(" · ".join(m.split("/")[-1] for m in models) or "—")
    parts.append(
        f"<div><span class='pill'>round <b>{rd}</b></span>"
        f"<span class='pill'>phase <b>{phase}</b></span>"
        f"<span class='pill'>goal <b>{goal}</b></span>"
        f"<span class='pill'>{nsec} sections decided</span></div>"
    )
    parts.append(
        "<div style='margin:4px 0'>"
        f"<span class='pill' style='border:1px solid {bcolor}'>"
        f"backend <b style='color:{bcolor}'>{_esc(blabel)}</b></span>"
        f"<span class='pill'>council <b>{models_str}</b></span></div>"
    )

    # === 🛰️ MISSION CONTROL — high-level, concise, at the very top ============
    times = _round_times()
    ms = _milestones()
    score_now = int(caps.get("score", 0) or 0)
    total_now = int(caps.get("total", 11) or 11)
    al = _alignment(rnd, total_now)
    done = score_now >= total_now and total_now > 0
    short = lambda m: str(m).split("/")[-1]  # noqa: E731
    nxt = next((n for n in (caps.get("all", []) or [])
                if n not in set(caps.get("passing", []) or [])), "—")
    step = ("✅ COMPLETE — all capabilities execute under the council's own interpreter"
            if done else f"building → next target <b>{_esc(nxt)}</b>")

    def card(title: str, inner: str) -> str:
        return ("<div style='flex:1;min-width:250px;background:#11141c;"
                "border:1px solid #2a2f3a;border-radius:10px;padding:12px 14px'>"
                f"<div style='color:#7aa2f7;font-weight:bold;margin-bottom:6px'>{title}</div>"
                f"{inner}</div>")

    # council card
    models_inner = "".join(
        f"<div>{'☁️' if '/' in m else '💻'} <b>{_esc(short(m))}</b> "
        f"<small>{_esc(m)}</small></div>" for m in models
    ) or "<small>—</small>"

    # version timeline (what each version did / is doing) — driven by versions.json
    vinfo = _versions()
    vlist = vinfo.get("versions", []) or []
    current_id = vinfo.get("current", "")
    if vlist:
        rows = []
        for v in vlist:
            cur = v.get("id") == current_id
            c = "#9ece6a" if cur else "#565f89"
            arrow = "▶ " if cur else ""
            rows.append(
                f"<div style='margin:4px 0;{'background:#16201a;border-left:3px solid #9ece6a;padding:4px 8px' if cur else 'padding:0 0 0 11px'}'>"
                f"<b style='color:{c}'>{arrow}{_esc(v.get('id'))}</b> "
                f"<b>{_esc(v.get('name'))}</b> "
                f"<small style='color:{c}'>· {_esc(v.get('status'))}</small><br>"
                f"<small>{_esc(v.get('did'))}</small></div>"
            )
        learned_inner = "".join(rows)
    else:
        learned_inner = "<small>versions.json not written yet</small>"

    # timing card (per-round ≈ same; the win is rounds-to-solution)
    reached10 = next((int(r) for r, t in ms if "10/11" in t and "reached" in t.lower()), None)
    reached11 = next((int(r) for r, t in ms if "11/11" in t and "reached" in t.lower()), None)
    span = (reached11 - reached10) if (reached10 and reached11) else None
    lt, ct = times["local"], times["cloud"]
    fmt = lambda s: f"{s // 60}m{s % 60:02d}s"  # noqa: E731
    timing_inner = (
        f"<div>local (Ollama 7–8B): <b>{fmt(lt['avg'])}</b>/round "
        f"<small>· {lt['n']} rounds · {lt['min']}–{lt['max']}s</small></div>"
        f"<div>cloud (OpenRouter): <b>{fmt(ct['avg']) if ct['n'] else '—'}</b>/round "
        f"<small>· {ct['n']} round(s)</small></div>"
        "<div style='margin-top:6px;color:#e0af68'>per-round wall-time ≈ <b>the same</b>. "
        "The leverage is <b>rounds-to-solution</b>:</div>"
        + (f"<div style='color:#9ece6a'>10/11 plateau held <b>{span} rounds</b> locally "
           "→ broken in <b>1</b> cloud round.</div>" if span else "")
    )

    # alignment / dissent card
    if al:
        align_inner = f"<div>last debate: <b>{_esc(al['title'])}</b></div>"
        align_inner += (f"<div style='color:#9ece6a'>✓ converged ({al['top']}/{total_now}): "
                        f"<b>{_esc(', '.join(short(m) for m in al['aligned']) or '—')}</b></div>")
        if al["partial"]:
            ps = ", ".join(f"{short(m)}({al['scores'][m]})" for m in al["partial"])
            align_inner += f"<div style='color:#e0af68'>~ partial: {_esc(ps)}</div>"
        if al["forfeit"]:
            align_inner += ("<div style='color:#f7768e'>✗ forfeited: "
                            f"{_esc(', '.join(short(m) for m in al['forfeit']))}</div>")
        align_inner += (f"<div style='margin-top:6px'>winner "
                        f"<b class='win'>{_esc(short(al['winner']))}</b> "
                        f"<small>{_esc(al['note'])}</small></div>")
    else:
        align_inner = "<small>no round logged yet</small>"

    # progression card (recent milestones)
    prog_inner = "".join(
        f"<div><small>r{_esc(r)}</small> {_esc(t[:64])}</div>" for r, t in ms[-5:]
    ) or "<small>—</small>"

    parts.append("<h2 style='color:#7dcfff;border-color:#2e4a5a'>🛰️ Mission control "
                 "<small>· the high-level view</small></h2>")
    parts.append(f"<div style='font-size:15px;margin:6px 0 2px'><b>step:</b> {step} "
                 f"&nbsp;·&nbsp; <b>round</b> {rd} &nbsp;·&nbsp; <b>phase</b> {phase} "
                 f"&nbsp;·&nbsp; <b class='win'>{score_now}/{total_now}</b> capabilities</div>")
    # full-width version timeline — which version we're on + what each did / is doing
    parts.append("<div style='background:#0d1119;border:1px solid #2a2f3a;border-radius:10px;"
                 "padding:10px 14px;margin:10px 0'>"
                 "<div style='color:#7dcfff;font-weight:bold;margin-bottom:4px'>"
                 "version timeline — what each version did, what we're doing now</div>"
                 f"{learned_inner}</div>")
    # North Star — the principle the project is built on (Principle of Least Generation)
    parts.append(
        "<div style='background:#0d1119;border:1px solid #2e4a5a;border-radius:10px;"
        "padding:10px 14px;margin:10px 0'>"
        "<div style='color:#7dcfff;font-weight:bold;margin-bottom:4px'>🌑 North Star — "
        "Principle of Least Generation <small>· route first, generate last</small></div>"
        "<div><b>MK</b> is the route-target, not a generator: English → gate → MK template "
        "(retrieved + slot-filled) → execute. The council/LLM is the <b>teacher</b> that "
        "mints execution-verified templates; then we <b>retrieve</b>, not generate.</div>"
        "<div style='margin-top:6px;color:#9ece6a'>proof on this domain "
        "(<small>plg_terminal.py</small>): the same 11/11 the council generated, at "
        "<b>0 generated tokens · 0.033 ms/program</b>, injection-proof by construction.</div>"
        "<div style='color:#565f89'><small>gate = embedding router on a compressed "
        "computing-context space · generation is the rare fallback for genuinely novel "
        "intents</small></div></div>"
    )
    parts.append("<div style='display:flex;flex-wrap:wrap;gap:10px;margin:10px 0 4px'>")
    parts.append(card("council · 5 models", models_inner))
    parts.append(card("round timing · local vs cloud", timing_inner))
    parts.append(card("alignment / dissent · last round", align_inner))
    parts.append(card("progression", prog_inner))
    parts.append("</div>")

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

    parts.append(_sql_findings_html())
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
