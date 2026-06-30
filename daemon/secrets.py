"""Centralized Secret Manager and Key Ring (vision §4.6).

Manages API keys for cloud backends. Reads from `~/.kinox/secrets.toml` and 
`os.environ`, pooling multiple keys for the same service. If a backend hits a 
429 Rate Limited or 401 Unauthorized, the key is marked exhausted and the 
executor's retry loop will automatically pull the next available key.
"""

from __future__ import annotations

import os
import tomllib
from pathlib import Path


class SecretManager:
    """Pools and dispenses API keys, managing exhaustion state."""

    def __init__(self, config_path: Path | None = None) -> None:
        self.config_path = config_path or Path("~/.kinox/secrets.toml").expanduser()
        self.pools: dict[str, list[str]] = {}
        self.exhausted: set[str] = set()
        self.load()

    def load(self) -> None:
        """Load secrets from TOML and the environment.

        Keys in TOML can be defined under a `[secrets]` section or at the top level.
        They can be a single string or a list of strings.
        The environment variable is always appended to the pool if present.
        """
        self.pools.clear()
        
        # 1. Load from TOML if it exists
        if self.config_path.exists():
            try:
                with self.config_path.open("rb") as f:
                    data = tomllib.load(f)
                
                # Check top-level and [secrets] table
                sources = [data]
                if isinstance(data.get("secrets"), dict):
                    sources.append(data["secrets"])
                
                for source in sources:
                    for key, val in source.items():
                        if key == "secrets" and isinstance(val, dict):
                            continue
                        if isinstance(val, str) and val.strip():
                            self.pools.setdefault(key, []).append(val.strip())
                        elif isinstance(val, list):
                            for v in val:
                                if isinstance(v, str) and v.strip():
                                    self.pools.setdefault(key, []).append(v.strip())
            except Exception:
                # Fail soft if malformed
                pass

        # 2. Layer environment variables on top
        for key in os.environ:
            val = os.environ[key]
            if val and val.strip():
                # Avoid duplicates in the pool
                pool = self.pools.setdefault(key, [])
                if val.strip() not in pool:
                    pool.append(val.strip())

    def get_token(self, env_name: str) -> str | None:
        """Return the first un-exhausted token for `env_name`, or None if all are exhausted."""
        pool = self.pools.get(env_name, [])
        for token in pool:
            if token not in self.exhausted:
                return token
        return None

    def mark_exhausted(self, token: str | None) -> None:
        """Mark a token as exhausted so it is skipped in future calls.
        
        Typically called when a backend returns a 429 Rate Limited or 401 Unauthorized.
        """
        if token:
            self.exhausted.add(token)

    def reset_exhaustion(self) -> None:
        """Clear the exhaustion state, allowing all keys to be retried."""
        self.exhausted.clear()

# Global singleton so all agent loops in the same daemon share exhaustion state
_GLOBAL_SECRETS = SecretManager()

def get_secret_manager() -> SecretManager:
    return _GLOBAL_SECRETS
