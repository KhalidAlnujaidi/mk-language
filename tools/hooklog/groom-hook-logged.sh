#!/usr/bin/env bash
# Transparent tee-logger for the GROOM (UserPromptSubmit) hook.
#
# Claude Code pipes the hook payload as JSON on stdin and reads the hook's
# stdout as added context. This wrapper captures BOTH the raw stdin (input) and
# the raw stdout (output) to a dump file, then passes stdout through UNCHANGED
# and preserves the real exit code — so behaviour is identical to calling the
# hook directly. Logging goes only to the file (never stdout/stderr), so it
# can't corrupt what Claude Code parses.
#
# To stop logging: point the UserPromptSubmit hook back at the raw command
# (see docs/session-report-2026-06-23.md) or restore a settings.json backup.
set -uo pipefail

LOG="${KINOX_HOOKLOG_DIR:-$HOME/.kinox/hooklog}/groom.log"
mkdir -p "$(dirname "$LOG")"

in_tmp="$(mktemp)"
out_tmp="$(mktemp)"
trap 'rm -f "$in_tmp" "$out_tmp"' EXIT

cat > "$in_tmp"   # capture stdin faithfully (temp file → no newline mangling)

# Run the real groom adapter with the captured stdin.
PYTHONPATH=/home/khalid/kinox /home/khalid/kinox/.venv/bin/python \
  -m adapters.claude_code < "$in_tmp" > "$out_tmp"
rc=$?

{
  echo "===== $(date -Iseconds)  GROOM (UserPromptSubmit)  exit=$rc ====="
  echo "--- INPUT (stdin JSON) ---"
  cat "$in_tmp"; echo
  echo "--- OUTPUT (stdout → added context) ---"
  cat "$out_tmp"; echo
  echo
} >> "$LOG"

cat "$out_tmp"    # pass the hook's stdout through unchanged
exit $rc
