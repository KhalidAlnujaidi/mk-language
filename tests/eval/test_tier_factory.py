# swarm-drafted (node=gemma-agent-1, model=Nemotron-14B); curated locally
import pytest
from kernel.contracts import Tier


def test_deterministic_not_model():
    tier = Tier.deterministic()
    assert not tier.is_model


def test_valid_where():
    tier = Tier.model("x", where="local")
    assert tier.model_name == "x"
    assert tier.where == "local"


def test_invalid_where_raises_value_error():
    with pytest.raises(ValueError):
        Tier.model("name", where="cloudless")  # type: ignore[arg-type]  # negative test
