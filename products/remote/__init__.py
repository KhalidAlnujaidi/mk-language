"""The remote-control surface — drive a kinox session from another device.

One dispatcher, two transports (the orca model): the broker keeps its local
Unix-socket transport (``daemon/server.py``); this package adds the **network**
transport in front of it, authenticated by a bearer token
(:mod:`daemon.remote_auth`). It lives in ``products/`` — not ``daemon/`` — because
the remote agent endpoint (P3) drives :func:`products.agent.run_agent`, and the
daemon may import only the kernel.
"""

from __future__ import annotations

from products.remote.server import RemoteConfig, assert_bind_safe, create_remote_app

__all__ = ["RemoteConfig", "assert_bind_safe", "create_remote_app"]
