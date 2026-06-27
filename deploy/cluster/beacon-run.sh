#!/usr/bin/env bash
# Launch Beacon 24/7: the autonomous self-development harness + the dashboard.
# Points the broker at the cluster inference Service and runs both detached.
#
#   deploy/cluster/beacon-run.sh start   # launch harness + dashboard (nohup)
#   deploy/cluster/beacon-run.sh stop    # stop both
#   deploy/cluster/beacon-run.sh status  # show pids + dashboard URL
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
VAR="$REPO/var/beacon"; mkdir -p "$VAR"
PY="${PYTHON:-$REPO/.venv/bin/python}"; [ -x "$PY" ] || PY=python3
# Cluster inference Service VIP (deploy/cluster/ollama-daemonset.yaml).
export KINOX_OLLAMA_URL="${KINOX_OLLAMA_URL:-http://10.43.33.57:11434/v1}"
# Bind on all interfaces so the dashboard is reachable over the tailnet
# (http://<tailscale-ip>:PORT) as well as locally. No secrets are served.
export BEACON_HOST="${BEACON_HOST:-0.0.0.0}"
export BEACON_PORT="${BEACON_PORT:-8808}"
TS_IP="$(tailscale ip -4 2>/dev/null | head -1)"
TAILNET_URL="${TS_IP:+http://$TS_IP:$BEACON_PORT}"

start() {
  cd "$REPO"
  nohup "$PY" -m products.beacon.harness >>"$VAR/harness.log" 2>&1 &
  echo $! >"$VAR/harness.pid"
  nohup "$PY" -m products.beacon.server  >>"$VAR/server.log"  2>&1 &
  echo $! >"$VAR/server.pid"
  sleep 1
  echo "harness pid=$(cat "$VAR/harness.pid")  local → http://127.0.0.1:$BEACON_PORT"
  [ -n "$TAILNET_URL" ] && echo "tailnet → $TAILNET_URL"
}
stop() {
  for n in harness server; do
    [ -f "$VAR/$n.pid" ] && kill "$(cat "$VAR/$n.pid")" 2>/dev/null && rm -f "$VAR/$n.pid" && echo "stopped $n" || true
  done
}
status() {
  for n in harness server; do
    if [ -f "$VAR/$n.pid" ] && kill -0 "$(cat "$VAR/$n.pid")" 2>/dev/null; then
      echo "$n: UP (pid $(cat "$VAR/$n.pid"))"; else echo "$n: down"; fi
  done
  echo "dashboard → http://$BEACON_HOST:$BEACON_PORT"
}
case "${1:-start}" in start) start;; stop) stop;; status) status;; restart) stop; start;; *) echo "usage: $0 {start|stop|status|restart}"; exit 1;; esac
