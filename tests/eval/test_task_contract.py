# swarm-drafted (node=kinox-swarm-3, model=Nemotron-14B); curated locally
import pytest
from kernel.contracts import Task, TaskKind

# Check Fuzzy (TAG) task missing budget_ms
with pytest.raises(ValueError):
    Task(TaskKind.TAG)

# Check Ground Truth (REDACT) with budget_ms provided
with pytest.raises(ValueError):
    Task(TaskKind.REDACT, budget_ms=500)

# Valid Task creation
assert Task(TaskKind.TAG, budget_ms=500)
