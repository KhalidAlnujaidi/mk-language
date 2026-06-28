"""Bearer-token authentication for the remote-control transport (P1).

The remote design (vision §7 / the orca model: *one dispatcher, two transports*)
exposes kinox over the tailnet so another device can drive a session. The local
transport (the broker's Unix socket) trusts the filesystem; the **network**
transport must authenticate every request. This module is that gate — and only
that gate: pure stdlib, no FastAPI, no I/O beyond reading token files, so the
policy is unit-tested without a server (thesis #1, deterministic ground truth).

The discipline mirrors orca's per-device auth-token file
(``runtime-rpc.ts``): a token is a high-entropy secret written ``0o600``; a
request proves possession via ``Authorization: Bearer <token>``; comparison is
constant-time. Fail-direction is CLOSED (thesis #2): a network request without a
valid token is denied, and binding to a non-loopback address with NO token
configured is a startup error (see :func:`requires_token`) — kinox never exposes
an unauthenticated network surface.
"""

from __future__ import annotations

import hmac
import secrets
from collections.abc import Mapping
from pathlib import Path

#: Token files carry this suffix; one file per paired device (orca's model).
TOKEN_SUFFIX = ".token"
#: Loopback hosts trusted without a token (local transport). NOT ``0.0.0.0`` —
#: bind-all is the most exposed address and always requires a token.
_LOOPBACK = frozenset({"", "127.0.0.1", "::1", "localhost"})


def generate_token() -> str:
    """A fresh high-entropy device token (URL-safe, ~256 bits)."""
    return secrets.token_urlsafe(32)


def load_tokens(token_dir: Path | None) -> frozenset[str]:
    """Every non-empty device token under *token_dir* (``*.token`` files).

    Returns an empty set when the directory is absent or holds no tokens — so an
    unconfigured install simply has no valid tokens (and thus no remote access),
    never a crash. Unreadable files are skipped (fail-soft on one bad file, not
    the whole set).
    """
    if token_dir is None or not token_dir.is_dir():
        return frozenset()
    tokens: set[str] = set()
    for path in sorted(token_dir.glob(f"*{TOKEN_SUFFIX}")):
        try:
            value = path.read_text(encoding="utf-8").strip()
        except OSError:
            continue
        if value:
            tokens.add(value)
    return frozenset(tokens)


def token_matches_any(provided: str, valid: frozenset[str]) -> bool:
    """True iff *provided* equals one of *valid*, compared in constant time.

    Uses :func:`hmac.compare_digest` per candidate and does NOT short-circuit on
    the first match, so the time taken does not reveal which (or whether an early)
    token matched. An empty *provided* or *valid* never matches.
    """
    if not provided or not valid:
        return False
    matched = False
    for candidate in valid:
        if hmac.compare_digest(provided, candidate):
            matched = True
    return matched


def bearer_from_headers(headers: Mapping[str, str]) -> str | None:
    """The token from an ``Authorization: Bearer <token>`` header, or ``None``.

    Case-insensitive on both the header name and the ``Bearer`` scheme (FastAPI's
    ``Request.headers`` is a case-insensitive mapping; plain dicts are handled too
    so the parser stays testable without a request object).
    """
    value: str | None = None
    for name, raw in headers.items():
        if name.lower() == "authorization":
            value = raw
            break
    if not value:
        return None
    parts = value.split(None, 1)
    if len(parts) != 2 or parts[0].lower() != "bearer":
        return None
    token = parts[1].strip()
    return token or None


def authorize(
    headers: Mapping[str, str],
    valid_tokens: frozenset[str],
    *,
    is_local: bool,
) -> str | None:
    """Authorize one request. Returns a denial reason, or ``None`` when allowed.

    *is_local* (a request arriving over the Unix socket / loopback) is trusted by
    the filesystem and needs no token. A network request is denied — fail-CLOSED —
    when no tokens are configured, when the bearer header is missing, or when the
    presented token matches none of *valid_tokens*. The reason is a short, safe
    string (it never echoes the presented token).
    """
    if is_local:
        return None
    if not valid_tokens:
        return "remote access is not configured (no device tokens)"
    presented = bearer_from_headers(headers)
    if presented is None:
        return "missing bearer token"
    if not token_matches_any(presented, valid_tokens):
        return "invalid token"
    return None


def requires_token(host: str | None) -> bool:
    """True when binding to *host* exposes a network surface that needs a token.

    Loopback / Unix-socket binds are local-trust and exempt; any other host is
    remote-reachable, so the server must have at least one device token before it
    binds (the fail-CLOSED startup check in :mod:`products.remote.server`).
    """
    return (host or "") not in _LOOPBACK
