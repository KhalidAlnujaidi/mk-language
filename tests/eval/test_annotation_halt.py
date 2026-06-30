# swarm-drafted (node=gemma-agent-4, model=Nemotron-14B); curated locally
from kernel.contracts import Annotation


def test_halt_sets_block_and_makes_blocked():
    anot = Annotation.halt("test reason")
    assert anot.is_blocked and anot.block == "test reason"


def test_passthrough_RETURNS_annotation_with_lines_but_unblocked():
    result = Annotation.passthrough(["context"])
    assert not result.is_blocked and result.lines == ["context"]
