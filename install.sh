#!/usr/bin/env bash
# Idempotent setup for kinox. Safe to re-run.
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$REPO_DIR"

if ! command -v uv >/dev/null 2>&1; then
  echo "error: uv is not installed. See https://docs.astral.sh/uv/ then re-run." >&2
  exit 1
fi

echo "==> Syncing the hermetic environment (uv sync)"
uv sync

# Symlink kx onto PATH if a standard user-bin dir exists and we're not already there.
BIN_DIR="${HOME}/.local/bin"
if [ -d "$BIN_DIR" ]; then
  ln -sf "$REPO_DIR/kx" "$BIN_DIR/kx"
  echo "==> Linked kx -> $BIN_DIR/kx"
else
  echo "==> $BIN_DIR not found; run kinox via ./kx from $REPO_DIR"
fi

echo "==> Done. Try: ./kx"
