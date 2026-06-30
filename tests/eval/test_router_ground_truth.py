# swarm-drafted (node=kinox-swarm-2, model=Nemotron-14B); curated locally
from kernel.contracts import Task, TaskKind
from kernel.manifest import probe
from kernel.router import route


def test_redact_routes_to_ground_truth():
    task = Task(TaskKind.REDACT)
    result_tier = route(task, probe())
    assert result_tier is not None  # GROUND_TRUTH always routes to a tier
    assert not result_tier.is_model, "Route didn't use ground truth for REDACT"
