"""Capability: Arity-Aware Command Safety.

A deterministic guard module for shell commands.
This checks the arity (prefix/positional structure) against an explicitly denied list.
"""

from __future__ import annotations

import enum

class ActionRule(enum.Enum):
    ALLOW = "allow"
    DENY = "deny"

# Catastrophic commands that are strictly hard-denied regardless of context.
DENY_PREFIXES: tuple[str, ...] = (
    "rm -rf",
    "mkfs",
    "drop database",
    "drop table",
    "history -c",
    "chmod -R 777",
    "chown -R",
)

def get_action_rule(cmd: str) -> ActionRule:
    """Evaluate the shell command and return the deterministic ActionRule.
    
    A command is explicitly DENIED if it matches catastrophic prefixes.
    Any command not explicitly denied is ALLOWED, bypassing interactive
    prompts per the heavily governed philosophy.
    """
    cleaned = cmd.strip()
    
    for deny_prefix in DENY_PREFIXES:
        if cleaned.startswith(deny_prefix):
            return ActionRule.DENY
            
    return ActionRule.ALLOW
