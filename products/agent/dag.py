"""Deterministic Decision-Graph (DAG) for guard and evaluation verdicts."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class DAGNode:
    """A node in a decision graph, capturing a judgment and its rationale.
    
    This turns a final verdict into a reproducible, inspectable tree (or DAG)
    of the decisions that led to it (CodeWhale / DeepEval harvest).
    """

    name: str
    decision: str
    reason: str
    children: list[DAGNode] = field(default_factory=list)

    def to_dict(self) -> dict[str, object]:
        """Serialize the node and its children."""
        res: dict[str, object] = {
            "name": self.name,
            "decision": self.decision,
            "reason": self.reason,
        }
        if self.children:
            res["children"] = [c.to_dict() for c in self.children]
        return res
