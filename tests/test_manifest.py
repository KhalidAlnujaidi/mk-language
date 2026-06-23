"""Tests for kernel.manifest — machine probe + available-tier list.

Design: behaviour tests that inject results rather than the real machine
(construct ``Manifest`` directly). The single integration test (``test_probe_*``)
hits the real machine but only asserts that ``probe()`` does not raise.
"""

from __future__ import annotations

from kernel.contracts import Tier
from kernel.manifest import CLOUD_DEFAULT_MODEL, LocalModel, Manifest


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


def test_probe_never_raises_and_returns_a_manifest() -> None:
    from kernel.manifest import probe

    m = probe()
    assert isinstance(m, Manifest)  # whatever the host, this must not raise
