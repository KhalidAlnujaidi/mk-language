#!/usr/bin/env bash
# Deploy a local dashboard (or any long-running service) as a systemd unit so it
# stays live 24/7 — survives reboot, auto-restarts on crash. The kinox default
# for every dashboard. See the `deploy-dashboard` skill.
#
# Usage:
#   tools/deploy-dashboard.sh --name <svc> --exec "<command>" [options]
#
#   --name NAME     systemd service name (required), e.g. kx-ui
#   --exec CMD      ExecStart command, ABSOLUTE paths (required)
#   --desc TEXT     unit Description (default: "<name> service")
#   --workdir DIR   WorkingDirectory (default: current dir)
#   --user USER     run as (default: SUDO_USER or current user)
#   --group GROUP   run as group (default: user's primary group)
#   --port PORT     if set, warn when the port is already bound
#
# Writes tools/<name>.service. If run as root it installs + enables + starts it;
# otherwise it prints the sudo commands. Free the port first (stop any nohup
# instance) or the start will fail to bind.
set -euo pipefail

NAME="" EXEC="" DESC="" WORKDIR="$(pwd)" RUNUSER="" RUNGROUP="" PORT=""
while [ $# -gt 0 ]; do
  case "$1" in
    --name)    NAME="$2"; shift 2;;
    --exec)    EXEC="$2"; shift 2;;
    --desc)    DESC="$2"; shift 2;;
    --workdir) WORKDIR="$2"; shift 2;;
    --user)    RUNUSER="$2"; shift 2;;
    --group)   RUNGROUP="$2"; shift 2;;
    --port)    PORT="$2"; shift 2;;
    *) echo "unknown arg: $1" >&2; exit 2;;
  esac
done
[ -n "$NAME" ] && [ -n "$EXEC" ] || { echo "required: --name and --exec" >&2; exit 2; }
[ -n "$DESC" ]     || DESC="$NAME service"
[ -n "$RUNUSER" ]  || RUNUSER="${SUDO_USER:-$(id -un)}"
[ -n "$RUNGROUP" ] || RUNGROUP="$(id -gn "$RUNUSER")"

UNIT_SRC="$WORKDIR/tools/$NAME.service"
mkdir -p "$WORKDIR/tools"
cat > "$UNIT_SRC" <<UNIT
[Unit]
Description=$DESC
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=$RUNUSER
Group=$RUNGROUP
WorkingDirectory=$WORKDIR
ExecStart=$EXEC
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
UNIT
echo "wrote unit: $UNIT_SRC"

if [ -n "$PORT" ] && command -v ss >/dev/null 2>&1 && ss -ltn 2>/dev/null | grep -q ":$PORT "; then
  echo "WARNING: something already listens on :$PORT — stop it first or the start will fail to bind."
fi

if [ "$(id -u)" -eq 0 ]; then
  cp "$UNIT_SRC" "/etc/systemd/system/$NAME.service"
  systemctl daemon-reload
  systemctl enable --now "$NAME.service"
  systemctl status "$NAME.service" --no-pager | head -8
else
  cat <<EOS

Not root — to install & start (24/7 + boot):
  sudo cp "$UNIT_SRC" /etc/systemd/system/$NAME.service
  sudo systemctl daemon-reload
  sudo systemctl enable --now $NAME.service
  systemctl status $NAME.service --no-pager
EOS
fi
