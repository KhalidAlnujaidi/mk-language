"""Capability loading/registration for kinox (Rule-Zero reuse of external assets)."""

from products.capabilities.registry import (
    AGENT,
    MCP_SERVER,
    SKILL,
    Capability,
    CapabilityRegistry,
    load_agents,
    load_mcp,
    load_skills,
)

__all__ = [
    "AGENT",
    "MCP_SERVER",
    "SKILL",
    "Capability",
    "CapabilityRegistry",
    "load_agents",
    "load_mcp",
    "load_skills",
]
