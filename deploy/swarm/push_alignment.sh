#!/usr/bin/env bash
# Push the kinox alignment + Bible to every running vast.ai swarm node.
# Places AGENTS.md and CLAUDE.md (same content) in /root and /workspace so any
# coding agent on the box inherits Rule Zero + project alignment from its CWD,
# alongside the canonical source-of-truth docs.
#
# Usage:  deploy/swarm/push_alignment.sh
# Requires: vastai CLI authed, ~/.ssh/id_ed25519 registered with the account.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(cd "$HERE/../.." && pwd)"
ALIGN="$HERE/AGENTS.md"
CONSTITUTION="$REPO/alignment/CONSTITUTION.md"
VISION="$REPO/vision.md"
REQ="$HOME/Desktop/project-alignment-requirement/PROJECT-ALIGNMENT-REQUIREMENT.md"

SSHOPTS=(-o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null
         -o ConnectTimeout=15 -i "$HOME/.ssh/id_ed25519")

# Enumerate running instances as "host port label" lines.
mapfile -t NODES < <(vastai show instances --raw 2>/dev/null | python3 -c '
import sys, json
for o in json.load(sys.stdin):
    if o.get("actual_status") == "running" and o.get("ssh_host"):
        print(o["ssh_host"], o["ssh_port"], o.get("label", o["id"]))
')

[ "${#NODES[@]}" -gt 0 ] || { echo "no running nodes"; exit 1; }

for line in "${NODES[@]}"; do
  read -r HOST PORT LABEL <<<"$line"
  echo "=== $LABEL ($HOST:$PORT) ==="
  ssh "${SSHOPTS[@]}" -p "$PORT" "root@$HOST" \
    'mkdir -p /root/kinox-alignment /workspace 2>/dev/null || true' || { echo "  ssh failed, skipping"; continue; }
  for dst in /root /workspace; do
    scp -P "$PORT" "${SSHOPTS[@]}" "$ALIGN" "root@$HOST:$dst/AGENTS.md"  >/dev/null 2>&1 || true
    scp -P "$PORT" "${SSHOPTS[@]}" "$ALIGN" "root@$HOST:$dst/CLAUDE.md"  >/dev/null 2>&1 || true
  done
  for doc in "$ALIGN" "$CONSTITUTION" "$VISION" "$REQ"; do
    [ -f "$doc" ] && scp -P "$PORT" "${SSHOPTS[@]}" "$doc" "root@$HOST:/root/kinox-alignment/" >/dev/null 2>&1 || true
  done
  ssh "${SSHOPTS[@]}" -p "$PORT" "root@$HOST" \
    'echo "  installed:"; ls -1 /root/AGENTS.md /root/CLAUDE.md /root/kinox-alignment/ 2>/dev/null | sed "s/^/    /"' || true
done
echo "=== alignment pushed to all running nodes ==="
