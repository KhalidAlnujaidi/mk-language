"""Tests for products.chat.app — chat TUI loop (unit, no TTY)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from kernel.manifest import LocalModel, Manifest
from kernel.metrics import MetricsSink
from products.chat.app import (
    _ollama_reachable,
    _parse_slices,
    _preflight,
    _QuitChat,
    chat_run,
    make_chat_action,
)

# --- /par slice parsing ------------------------------------------------------


def test_parse_slices_two_agents_with_owned_paths() -> None:
    specs = _parse_slices("write ui @ products/chat ;; write api @ daemon/brain.py")
    assert specs == [
        ("write ui", ("products/chat",)),
        ("write api", ("daemon/brain.py",)),
    ]


def test_parse_slices_multiple_owned_paths() -> None:
    specs = _parse_slices("do it @ a.py, b.py , c/")
    assert specs == [("do it", ("a.py", "b.py", "c/"))]


def test_parse_slices_no_at_is_read_only_slice() -> None:
    assert _parse_slices("just read") == [("just read", ())]


def test_parse_slices_empty_returns_none() -> None:
    assert _parse_slices("   ") is None


def test_parse_slices_empty_task_returns_none() -> None:
    assert _parse_slices("@ a.py") is None


def _manifest(**kw: object) -> Manifest:
    base: dict[str, object] = dict(
        cpu_count=8,
        ram_gb=32.0,
        gpu_vram_gb=12.0,
        local_models=(),
        cloud_available=False,
    )
    base.update(kw)
    return Manifest(**base)  # type: ignore[arg-type]


# --- pre-flight tests --------------------------------------------------------


def test_ollama_reachable_false_when_no_url() -> None:
    """Returns False when Ollama URL is not configured."""
    with patch("kernel.manifest.local_backend_urls", return_value={}):
        assert _ollama_reachable(_manifest()) is False


def test_ollama_reachable_handles_connection_error() -> None:
    """Returns False when the API endpoint is unreachable."""
    with (
        patch(
            "kernel.manifest.local_backend_urls",
            return_value={"ollama": "http://127.0.0.1:11434/v1"},
        ),
        patch("urllib.request.urlopen", side_effect=OSError("refused")),
    ):
        assert _ollama_reachable(_manifest()) is False


def test_preflight_no_models_at_all() -> None:
    """Returns a diagnostic when neither a cloud brain (disabled under the
    hermetic conftest) nor a local model is available."""
    m = _manifest(local_models=())
    error = _preflight(m)
    assert error is not None
    assert "No model available" in error


def test_preflight_does_not_block_on_vram() -> None:
    """Preflight does not gate on VRAM — Ollama manages its own memory.
    Even a 24 GB model on an 8 GB GPU passes (Ollama offloads to CPU)."""
    big = LocalModel("big-model", vram_gb_required=24.0)
    m = _manifest(local_models=(big,), gpu_vram_gb=8.0)
    with patch("products.chat.app._ollama_reachable", return_value=True):
        error = _preflight(m)
    assert error is None  # passes — VRAM is Ollama's problem


def test_preflight_ollama_unreachable() -> None:
    """Returns diagnostic when models fit but API is down."""
    model = LocalModel("gemma", vram_gb_required=5.0)
    m = _manifest(local_models=(model,), gpu_vram_gb=12.0)
    with patch("products.chat.app._ollama_reachable", return_value=False):
        error = _preflight(m)
    assert error is not None
    assert "API endpoint is not responding" in error


def test_preflight_passes_when_all_checks_ok() -> None:
    """Returns None when models exist, fit, and API is reachable."""
    model = LocalModel("gemma", vram_gb_required=5.0)
    m = _manifest(local_models=(model,), gpu_vram_gb=12.0)
    with patch("products.chat.app._ollama_reachable", return_value=True):
        error = _preflight(m)
    assert error is None


# --- chat_run tests -----------------------------------------------------------


def test_non_tty_returns_immediately() -> None:
    """Passing is_tty=False prints a plan line and returns 0 without blocking."""
    rc = chat_run(
        manifest=_manifest(),
        sink=MetricsSink(Path("/dev/null")),
        cwd=Path("/tmp"),
        is_tty=False,
    )
    assert rc == 0


def test_preflight_failure_returns_to_hub() -> None:
    """When pre-flight fails, a diagnostic is shown and 0 is returned."""
    m = _manifest(local_models=())  # no models
    rc = chat_run(
        manifest=m,
        sink=MetricsSink(Path("/dev/null")),
        cwd=Path("/tmp"),
        is_tty=True,
    )
    assert rc == 0  # returned to hub, no crash


def test_quit_chat_exception_is_caught() -> None:
    """chat_run catches _QuitChat and returns 0 (doesn't crash the hub)."""
    model = LocalModel("gemma", vram_gb_required=5.0)
    m = _manifest(local_models=(model,), gpu_vram_gb=12.0)
    with patch("products.chat.app._preflight", return_value=None), \
         patch("products.chat.app._welcome"), \
         patch("products.chat.app._loop", side_effect=_QuitChat()):
        rc = chat_run(
            manifest=m,
            sink=MetricsSink(Path("/dev/null")),
            cwd=Path("/tmp"),
            is_tty=True,
        )
    assert rc == 0


def test_make_chat_action_returns_callable() -> None:
    """make_chat_action builds a zero-arg Action for the hub."""
    action = make_chat_action(
        manifest=_manifest(),
        sink=MetricsSink(Path("/dev/null")),
        cwd=Path("/tmp"),
        is_tty=False,
    )
    assert callable(action)
    rc = action()
    assert rc == 0
