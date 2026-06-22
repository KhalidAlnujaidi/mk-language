# swarm-drafted (node=gemma-agent-2, model=Nemotron-14B); curated locally
# Behavioral: a cue at the start (on a word/punct boundary) within the word cap
# marks a correction; a cue merely embedded ("nominal") does not. (Fixed: the
# draft had a typo (looks_likeCorrection) and a loop with wrong expectations.)
from kernel.corrections import looks_like_correction


def test_correction_cue_at_start():
    assert looks_like_correction("add a button", "no, make it red")
    assert looks_like_correction("add a button", "actually, revert that")
    assert looks_like_correction("add a button", "nope")
    assert looks_like_correction("add a button", "i meant the other one")


def test_not_a_correction():
    # cue must be on a boundary: "nominal" starts with "no" but isn't a cue
    assert not looks_like_correction("add a button", "nominal spacing tweak")
    assert not looks_like_correction("add a button", "irrelevant follow-up text")


def test_correction_requires_prev_and_brevity():
    assert not looks_like_correction("", "no, change it")  # no prior turn
    assert not looks_like_correction(
        "prev", " ".join(["no"] + ["word"] * 13)
    )  # too long
