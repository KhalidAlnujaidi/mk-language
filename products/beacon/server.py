"""Beacon dashboard — a local, stdlib-only window onto the 24/7 loop.

No web framework (Rule Zero: ``http.server`` already serves HTML + JSON). One
self-contained page polls ``/api/state`` every few seconds and renders fleet
health, the axiom pledge, and the ledger — KEPT evolutions highlighted green,
pitfalls documented with their cause, AIOS corpus hits shown as reuse wins.

Run: ``python -m products.beacon.server`` (defaults to 127.0.0.1:8808).
"""

from __future__ import annotations

import json
import os
import time
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from products.beacon.harness import CLUSTER_URL, LEDGER_PATH
from products.beacon.ledger import Ledger

HOST = os.environ.get("BEACON_HOST", "127.0.0.1")
PORT = int(os.environ.get("BEACON_PORT", "8808"))
# Probe the cluster Service's bare root (strip the OpenAI ``/v1`` suffix).
_CLUSTER_BASE = CLUSTER_URL.rsplit("/v1", 1)[0]


def _ping_cluster() -> dict[str, object]:
    """Best-effort liveness of the cluster inference Service."""
    try:
        with urllib.request.urlopen(_CLUSTER_BASE + "/api/version", timeout=4) as r:
            ver = json.loads(r.read().decode()).get("version", "?")
        with urllib.request.urlopen(_CLUSTER_BASE + "/api/tags", timeout=4) as r:
            tags = json.loads(r.read().decode()).get("models", [])
        return {"up": True, "version": ver, "models": [m.get("name") for m in tags]}
    except Exception:
        return {"up": False, "version": None, "models": []}


def build_state() -> dict[str, object]:
    """Assemble the dashboard payload from the ledger + a live cluster ping."""
    ledger = Ledger(LEDGER_PATH)
    rows = ledger.read()
    pledges = [r for r in rows if r.get("kind") == "pledge"]
    health = [r for r in rows if r.get("kind") == "health"]
    last_health = health[-1] if health else {}
    last_ts = rows[-1]["ts"] if rows else None
    idle = last_ts is None or (time.time() - last_ts) > 120
    return {
        "now": time.time(),
        "status": "idle" if idle else "running",
        "last_event_age_s": round(time.time() - last_ts, 1) if last_ts else None,
        "cluster": _ping_cluster(),
        "pledge": pledges[-1] if pledges else None,
        "counts": {
            "findings": sum(1 for r in rows if r.get("kind") == "finding"),
            "pitfalls": sum(1 for r in rows if r.get("kind") == "pitfall"),
            "corpus_hits": sum(1 for r in rows if r.get("kind") == "corpus_hit"),
            "cycles": sum(1 for r in rows if r.get("kind") == "cycle"),
        },
        "health": last_health,
        "tps_series": [h.get("tps") for h in health[-40:] if h.get("tps") is not None],
        "findings": [r for r in rows if r.get("kind") == "finding"][-20:][::-1],
        "pitfalls": [r for r in rows if r.get("kind") == "pitfall"][-20:][::-1],
        "corpus_hits": [r for r in rows if r.get("kind") == "corpus_hit"][-12:][::-1],
    }


PAGE = """<!doctype html><html><head><meta charset=utf-8>
<title>Beacon — kinox self-development</title>
<style>
 :root{--bg:#0b0f14;--card:#141b24;--ink:#dbe4ee;--mut:#7c8aa0;--grn:#2ecc71;--amb:#f1c40f;--red:#e74c3c;--blu:#3aa0ff}
 *{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:14px/1.5 ui-monospace,Menlo,Consolas,monospace}
 header{display:flex;align-items:center;gap:14px;padding:16px 22px;border-bottom:1px solid #1e2935}
 h1{font-size:18px;margin:0;letter-spacing:.5px}.dot{width:11px;height:11px;border-radius:50%}
 .run{background:var(--grn);box-shadow:0 0 10px var(--grn)}.idle{background:var(--amb)}.down{background:var(--red)}
 .wrap{padding:18px 22px;display:grid;gap:16px;grid-template-columns:repeat(auto-fit,minmax(330px,1fr))}
 .card{background:var(--card);border:1px solid #1e2935;border-radius:10px;padding:14px 16px}
 .card h2{font-size:12px;text-transform:uppercase;letter-spacing:1px;color:var(--mut);margin:0 0 10px}
 .kpi{display:flex;gap:18px;flex-wrap:wrap}.kpi div{text-align:center}.kpi b{display:block;font-size:22px}
 .find{border-left:3px solid var(--grn);background:#11241a}.pit{border-left:3px solid var(--red);background:#241313}
 .hit{border-left:3px solid var(--blu);background:#0f1d2b}
 .row{padding:8px 10px;margin:7px 0;border-radius:6px;font-size:13px}
 .mut{color:var(--mut)}.grn{color:var(--grn)}.amb{color:var(--amb)}.red{color:var(--red)}.blu{color:var(--blu)}
 .ax{margin:4px 0;padding-left:14px;text-indent:-14px}.spark{font-size:11px;color:var(--grn);letter-spacing:1px;word-break:break-all}
 .empty{color:var(--mut);font-style:italic}
</style></head><body>
<header><span id=dot class=dot></span><h1>BEACON</h1>
 <span class=mut>kinox · governed 24/7 self-development · Bible: <span class=blu id=bible>AIOS</span></span>
 <span class=mut style=margin-left:auto id=status></span></header>
<div class=wrap>
 <div class=card><h2>Fleet</h2><div class=kpi id=kpi></div><div style=margin-top:10px class=spark id=spark></div></div>
 <div class=card><h2>Pledge to the axioms</h2><div id=pledge></div></div>
 <div class=card style=grid-column:1/-1><h2>🟢 Findings — kept evolutions (benefit produced)</h2><div id=findings></div></div>
 <div class=card><h2>Pitfalls — documented, not repeated</h2><div id=pitfalls></div></div>
 <div class=card><h2>AIOS corpus hits — reuse wins</h2><div id=hits></div></div>
</div>
<script>
const $=id=>document.getElementById(id);
const fmtAge=s=>s==null?'—':s<60?s.toFixed(0)+'s':(s/60).toFixed(1)+'m';
async function tick(){
 let s; try{s=await (await fetch('/api/state')).json()}catch(e){return}
 const cl=s.cluster||{}; const up=cl.up;
 $('dot').className='dot '+(!up?'down':s.status==='running'?'run':'idle');
 $('status').textContent=(up?'cluster up · '+(cl.models||[]).join(', '):'cluster DOWN')+' · last event '+fmtAge(s.last_event_age_s);
 if(s.pledge&&s.pledge.bible)$('bible').textContent=s.pledge.bible;
 const h=s.health||{}, c=s.counts||{};
 $('kpi').innerHTML=[['cycles',c.cycles],['🟢 findings',c.findings],['pitfalls',c.pitfalls],
   ['corpus hits',c.corpus_hits],['tok/s',h.tps??'—'],['corpus',h.corpus_skills??'—'],
   ['uptime',h.uptime_s?fmtAge(h.uptime_s):'—']].map(([k,v])=>`<div><b>${v??0}</b><span class=mut>${k}</span></div>`).join('');
 $('spark').textContent=(s.tps_series||[]).map(t=>'▁▂▃▄▅▆▇█'[Math.min(7,Math.round(t/4))]||'▁').join('')||'';
 const p=s.pledge;
 $('pledge').innerHTML=p?`<div class=mut style=margin-bottom:6px>“${p.oath}”</div>`+
   (p.axioms||[]).map(a=>`<div class=ax>· ${a}</div>`).join(''):'<div class=empty>no pledge yet</div>';
 const card=(arr,cls,fn)=>arr&&arr.length?arr.map(fn).join(''):'<div class=empty>nothing yet</div>';
 $('findings').innerHTML=card(s.findings,'find',f=>`<div class="row find"><span class=grn>✔ KEPT</span> <b>${f.skill||''}</b>
   <span class=mut>· challenge ${f.challenge} · cycle ${f.cycle}</span><div class=mut>${f.note||''}</div></div>`);
 $('pitfalls').innerHTML=card(s.pitfalls,'pit',p=>`<div class="row pit"><span class=red>${p.kind_of||'pitfall'}</span>
   <span class=mut>· ${p.challenge||''} · cycle ${p.cycle}</span><div class=mut>${p.cause||''}</div></div>`);
 $('hits').innerHTML=card(s.corpus_hits,'hit',h=>`<div class="row hit"><span class=blu>${h.bible}</span>
   <span class=mut>· ${h.challenge} · cycle ${h.cycle}</span><div class=mut>${(h.sources||[]).join(', ')}</div></div>`);
}
tick();setInterval(tick,5000);
</script></body></html>"""


class Handler(BaseHTTPRequestHandler):
    def _send(self, body: bytes, ctype: str) -> None:
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802 — stdlib naming
        if self.path.startswith("/api/state"):
            self._send(json.dumps(build_state()).encode(), "application/json")
        elif self.path in ("/", "/index.html"):
            self._send(PAGE.encode(), "text/html; charset=utf-8")
        else:
            self.send_error(404)

    def log_message(self, *_: object) -> None:  # silence per-request stderr spam
        return


def main() -> None:
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    print(f"Beacon dashboard → http://{HOST}:{PORT}  (ledger: {LEDGER_PATH})")
    server.serve_forever()


if __name__ == "__main__":
    main()
