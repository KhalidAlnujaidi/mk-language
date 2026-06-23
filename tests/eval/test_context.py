# golden eval — context stage (products/groom/stages/context.py)
# Behavioral: gathering context in a non-git directory degrades to empty rather
# than raising (fail-direction SOFT for an optimizer stage).
from pathlib import Path

from products.groom.stages.context import gather


def test_context_is_empty_outside_a_git_repo(tmp_path: Path):
    result = gather(tmp_path)  # tmp_path is not a git repo
    assert result.lines == ()
