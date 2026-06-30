"""Tests for kernel.manifest — machine probe + available-tier list.

Design: behaviour tests that inject results rather than the real machine
(construct ``Manifest`` directly). The single integration test (``test_probe_*``)
hits the real machine but only asserts that ``probe()`` does not raise.
"""

from __future__ import annotations

import pytest
from kernel.contracts import Tier
from kernel.manifest import (
    CLOUD_DEFAULT_MODEL,
    LocalModel,
    Manifest,
    local_backend_urls,
)


def _m(**kw: object) -> Manifest:
    base: dict[str, object] = dict(
        cpu_count=8,
        ram_gb=60.0,
        gpu_vram_gb=20.0,
        local_models=(),
        cloud_available=False,
    )
    base.update(kw)
    return Manifest(**base)  # type: ignore[arg-type]


def test_unknown_capabilities_are_none_never_zero() -> None:
    m = Manifest(
        cpu_count=None,
        ram_gb=None,
        gpu_vram_gb=None,
        local_models=(),
        cloud_available=False,
    )
    assert m.gpu_vram_gb is None  # unknown, not 0.0


def test_fitting_excludes_models_with_unknown_vram() -> None:
    m = _m(local_models=(LocalModel("mystery", None),))
    assert m.fitting_local_models() == ()


def test_fitting_includes_only_models_that_fit_vram() -> None:
    models = (
        LocalModel("big", 40.0),
        LocalModel("small", 4.0),
        LocalModel("mid", 12.0),
    )
    m = _m(gpu_vram_gb=20.0, local_models=models)
    # smallest-first, big excluded
    assert [x.name for x in m.fitting_local_models()] == ["small", "mid"]


def test_no_gpu_means_no_local_fits() -> None:
    m = _m(gpu_vram_gb=None, local_models=(LocalModel("small", 4.0),))
    assert m.fitting_local_models() == ()


def test_available_tiers_always_starts_with_deterministic() -> None:
    assert _m().available_tiers()[0] == Tier.deterministic()


def test_available_tiers_adds_cloud_only_when_available() -> None:
    no_cloud = _m(cloud_available=False).available_tiers()
    assert all(t.where != "cloud" for t in no_cloud)
    with_cloud = _m(cloud_available=True).available_tiers()
    assert any(
        t.model_name == CLOUD_DEFAULT_MODEL and t.where == "cloud"
        for t in with_cloud
    )


def test_local_model_defaults_to_ollama_backend() -> None:
    # Backward compatible: positional construction still works; backend is ollama.
    assert LocalModel("mistral", 4.0).backend == "ollama"


def test_available_tiers_tag_each_local_models_backend() -> None:
    # A vLLM-served model produces a tier the broker can route to vLLM.
    models = (
        LocalModel("ollama-model", 4.0, backend="ollama"),
        LocalModel("vllm-model", 6.0, backend="vllm"),
    )
    tiers = _m(gpu_vram_gb=20.0, local_models=models).available_tiers()
    local = [t for t in tiers if t.is_model and t.where == "local"]
    by_name = {t.model_name: t.backend for t in local}
    assert by_name == {"ollama-model": "ollama", "vllm-model": "vllm"}


def test_cloud_tier_backend_is_anthropic() -> None:
    with_cloud = _m(cloud_available=True).available_tiers()
    cloud = next(t for t in with_cloud if t.where == "cloud")
    assert cloud.backend == "anthropic"


# --- Canonical local-backend endpoints (single source of truth) --------------


def test_local_backend_urls_has_the_three_local_backends() -> None:
    urls = local_backend_urls()
    assert set(urls) == {"ollama", "vllm", "llamacpp"}
    assert urls["ollama"].endswith(":11434/v1")
    assert urls["vllm"].endswith(":8000/v1")
    assert urls["llamacpp"].endswith(":8080/v1")


def test_local_backend_urls_env_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("KINOX_LLAMACPP_URL", "http://box:9999/v1")
    assert local_backend_urls()["llamacpp"] == "http://box:9999/v1"


# --- Probing OpenAI-compatible /v1/models endpoints (via probe()) ------------
#
# The HTTP fetch is the injectable seam (``_http_get_json``); these tests drive
# the public ``probe()`` with that seam stubbed, so no live server is touched and
# discovery + backend-tagging + merging are all exercised end-to-end.


def test_probe_discovers_and_tags_openai_backends(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import kernel.manifest as mod

    monkeypatch.setattr(mod, "_probe_local_models", lambda: ())
    urls = mod.local_backend_urls()

    def fake_get(url: str, *, timeout: float) -> object | None:
        if url == urls["vllm"].rstrip("/") + "/models":
            return {"data": [{"id": "qwen-7b"}, {"id": "llama-8b"}]}
        return None  # llama.cpp not running

    monkeypatch.setattr(mod, "_http_get_json", fake_get)
    tagged = {(m.name, m.backend) for m in mod.probe().local_models}
    assert ("qwen-7b", "vllm") in tagged
    assert ("llama-8b", "vllm") in tagged
    assert all(b != "llamacpp" for _, b in tagged)  # unreachable contributes none


def test_probe_unreachable_backends_contribute_nothing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import kernel.manifest as mod

    monkeypatch.setattr(
        mod, "_probe_local_models", lambda: (LocalModel("ollama-m", None, "ollama"),)
    )

    def unreachable(url: str, *, timeout: float) -> object | None:
        return None

    monkeypatch.setattr(mod, "_http_get_json", unreachable)
    backends = {m.backend for m in mod.probe().local_models}
    assert backends == {"ollama"}  # only the CLI-probed Ollama survives


def test_probe_malformed_backend_response_contributes_nothing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import kernel.manifest as mod

    monkeypatch.setattr(mod, "_probe_local_models", lambda: ())

    def malformed(url: str, *, timeout: float) -> object:
        return {"unexpected": "shape"}

    monkeypatch.setattr(mod, "_http_get_json", malformed)
    assert mod.probe().local_models == ()


def test_probe_never_raises_and_returns_a_manifest() -> None:
    from kernel.manifest import probe

    m = probe()
    assert isinstance(m, Manifest)  # whatever the host, this must not raise
