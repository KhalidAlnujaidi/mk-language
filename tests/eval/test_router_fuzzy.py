# golden eval — router FUZZY path (kernel/router.py)
# Behavioral: a FUZZY task never runs as plain code — it routes to a model tier
# (local preferred, else cloud) or None when none fits, but NEVER to the
# deterministic (no-model) tier. Complements test_router_ground_truth.
from kernel.contracts import Task, TaskKind
from kernel.manifest import probe
from kernel.router import route


def test_fuzzy_task_never_routes_to_deterministic():
    tier = route(Task(TaskKind.TAG, budget_ms=500), probe())
    # either nothing fits (None) or a real model tier — never plain code
    assert tier is None or tier.is_model is True
