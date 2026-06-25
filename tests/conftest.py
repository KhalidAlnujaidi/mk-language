"""Shared pytest fixtures for the kinox suite.

kinox's brain is **cloud-first** in production (``glm-5.2`` on z.ai — see
``daemon.brain``). The test suite, however, must stay hermetic: no test may make
a real network call to a cloud provider (the constitution: tests run offline, no
network, no GPU). So by default we pin ``KINOX_BRAIN=local`` for every test,
disabling the cloud brain and exercising the local path deterministically.

Tests that specifically verify the cloud brain (``tests/test_brain.py``,
``tests/test_broker_backends.py``) override this with their own ``monkeypatch``
— a later ``setenv``/``delenv`` in the test body wins over this autouse default.
"""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _hermetic_local_brain(  # pyright: ignore[reportUnusedFunction]  # pytest autouse
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Disable the cloud brain by default so the suite never calls z.ai."""
    monkeypatch.setenv("KINOX_BRAIN", "local")
