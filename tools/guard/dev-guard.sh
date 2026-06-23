#!/usr/bin/env bash
# Dev-role guard gate (PreToolUse on the file-editing tools).
#
# Fast-path: if this session is NOT a developer session, exit immediately —
# zero cost, no Python startup. Only when KINOX_ROLE=developer do we hand the
# payload to the Python guard, which denies edits to framework code (anything
# under the kinox repo outside projects/). stdin passes straight through.
#
# Registered globally, so it must be a no-op for admin/normal sessions.
set -uo pipefail

[ "${KINOX_ROLE:-}" = "developer" ] || exit 0

exec env PYTHONPATH=/home/khalid/kinox \
  /home/khalid/kinox/.venv/bin/python -m adapters.guard
