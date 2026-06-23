#!/usr/bin/env bash
# Transparent tee-logger for the RTK (PreToolUse: Bash) hook.
#
# Claude Code pipes the Bash tool-call payload as JSON on stdin; `rtk hook
# claude` reads it and emits its decision/rewrite on stdout. This wrapper
# captures BOTH the raw stdin (input) and the raw stdout (output) to a dump
# file, then passes stdout through UNCHANGED and preserves the real exit code —
# identical behaviour to calling `rtk hook claude` directly. Logging goes only
# to the file, never to stdout/stderr.
#
# To stop logging: point the PreToolUse hook back at "rtk hook claude" (or run
# `rtk init -g` again / restore a settings.json backup).
set -uo pipefail

LOG="${KINOX_HOOKLOG_DIR:-$HOME/.kinox/hooklog}/rtk.log"
mkdir -p "$(dirname "$LOG")"

RTK="${RTK_BIN:-/home/khalid/.local/bin/rtk}"

in_tmp="$(mktemp)"
out_tmp="$(mktemp)"
trap 'rm -f "$in_tmp" "$out_tmp"' EXIT

cat > "$in_tmp"   # capture stdin faithfully

# Run the real rtk hook with the captured stdin, in the inherited cwd.
"$RTK" hook claude < "$in_tmp" > "$out_tmp"
rc=$?

{
  echo "===== $(date -Iseconds)  RTK (PreToolUse:Bash)  exit=$rc ====="
  echo "--- INPUT (stdin JSON) ---"
  cat "$in_tmp"; echo
  echo "--- OUTPUT (stdout → tool rewrite/decision) ---"
  cat "$out_tmp"; echo
  echo
} >> "$LOG"

cat "$out_tmp"    # pass rtk's stdout through unchanged
exit $rc
