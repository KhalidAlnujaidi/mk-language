import os
from pathlib import Path
import pytest

from daemon.secrets import SecretManager

def test_secret_manager_pooling(tmp_path: Path):
    """Test pooling from TOML and environ."""
    # Write dummy secrets.toml
    config_path = tmp_path / "secrets.toml"
    config_path.write_text(
        "[secrets]\\n"
        "MY_SERVICE_KEY = [\\'key1\\', \\'key2\\']\\n"
        "OTHER_KEY = \\'other1\\'\\n"
    )

    # Inject environ
    os.environ["MY_SERVICE_KEY"] = "key3"
    os.environ["NEW_KEY"] = "new1"

    try:
        manager = SecretManager(config_path=config_path)

        # Should pool both TOML and environ
        assert manager.pools["MY_SERVICE_KEY"] == ["key1", "key2", "key3"]
        assert manager.pools["OTHER_KEY"] == ["other1"]
        assert manager.pools["NEW_KEY"] == ["new1"]

        # get_token should return the first available
        token = manager.get_token("MY_SERVICE_KEY")
        assert token == "key1"

        # Mark exhausted
        manager.mark_exhausted(token)
        token2 = manager.get_token("MY_SERVICE_KEY")
        assert token2 == "key2"

        manager.mark_exhausted(token2)
        token3 = manager.get_token("MY_SERVICE_KEY")
        assert token3 == "key3"

        manager.mark_exhausted(token3)
        assert manager.get_token("MY_SERVICE_KEY") is None

        # Reset
        manager.reset_exhaustion()
        assert manager.get_token("MY_SERVICE_KEY") == "key1"

    finally:
        os.environ.pop("MY_SERVICE_KEY", None)
        os.environ.pop("NEW_KEY", None)

def test_secret_manager_malformed_toml(tmp_path: Path):
    """Ensure malformed TOML doesn't crash the manager (fails soft)."""
    config_path = tmp_path / "secrets.toml"
    config_path.write_text("this is not toml")

    os.environ["ONLY_ENV"] = "env1"
    try:
        manager = SecretManager(config_path=config_path)
        assert manager.pools["ONLY_ENV"] == ["env1"]
    finally:
        os.environ.pop("ONLY_ENV", None)
