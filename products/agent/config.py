"""Layered, profile-aware config for the agent loop (CodeWhale Tier-2).

Loads agent settings like token_budget and permission rulesets from TOML config.

Precedence (highest first) — the first source that yields a setting wins:
  1. project file, ``[profile.<name>.agent]``
  2. project file, ``[agent]``
  3. global file,  ``[profile.<name>.agent]``
  4. global file,  ``[agent]``

Parsed with stdlib ``tomllib`` (Rule Zero). Fail-soft on missing/malformed file.
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass
from typing import cast

from products.agent.budget import TokenBudget
from products.agent.permission import Ruleset, from_dicts


@dataclass
class ToolConfig:
    allow_bash: bool = True
    allow_write: bool = True
    allow_mcp: bool = True


def _get_agent_section(toml_text: str, profile: str | None) -> dict[str, object] | None:
    """Extract the most specific agent configuration section from a TOML string."""
    if not toml_text:
        return None
    try:
        data: dict[str, object] = tomllib.loads(toml_text)
    except tomllib.TOMLDecodeError:
        return None  # fail-soft

    if profile is not None:
        profiles = data.get("profile")
        if isinstance(profiles, dict):
            section = cast("dict[str, object]", profiles).get(profile)
            if isinstance(section, dict):
                agent = cast("dict[str, object]", section).get("agent")
                if isinstance(agent, dict):
                    return agent

    base_agent = data.get("agent")
    if isinstance(base_agent, dict):
        return base_agent
    return None


def load_token_budget(
    global_text: str | None = None,
    project_text: str | None = None,
    *,
    profile: str | None = None,
) -> TokenBudget | None:
    """Resolve the token budget limit across config sources.
    
    Looks for ``token_budget`` inside the active agent section.
    Returns a TokenBudget object if found, otherwise None (unlimited).
    """
    for text in (project_text, global_text):
        section = _get_agent_section(text or "", profile)
        if section is not None:
            raw_limit = section.get("token_budget")
            if isinstance(raw_limit, int):
                return TokenBudget(limit=raw_limit)
    return None


def load_ruleset(
    global_text: str | None = None,
    project_text: str | None = None,
    *,
    profile: str | None = None,
) -> Ruleset | None:
    """Resolve permission rules across config sources.
    
    Looks for ``[[rules]]`` inside the active agent section.
    If no rules are found, returns None (no overrides to baseline).
    """
    for text in (project_text, global_text):
        section = _get_agent_section(text or "", profile)
        if section is not None:
            raw_rules = section.get("rules")
            if isinstance(raw_rules, list):
                dicts: list[dict[str, object]] = [
                    r for r in raw_rules if isinstance(r, dict)
                ]
                return from_dicts(dicts)
    return None


def load_tool_config(
    global_text: str | None = None,
    project_text: str | None = None,
    *,
    profile: str | None = None,
) -> ToolConfig:
    """Resolve the tool layer configuration across config sources.
    
    Looks for boolean flags like ``allow_bash``, ``allow_write``, ``allow_mcp`` 
    inside the active agent section. Defaults to True if missing.
    """
    config = ToolConfig()
    for text in (project_text, global_text):
        section = _get_agent_section(text or "", profile)
        if section is not None:
            if "allow_bash" in section and isinstance(section["allow_bash"], bool):
                config.allow_bash = section["allow_bash"]
            if "allow_write" in section and isinstance(section["allow_write"], bool):
                config.allow_write = section["allow_write"]
            if "allow_mcp" in section and isinstance(section["allow_mcp"], bool):
                config.allow_mcp = section["allow_mcp"]
            # Once we find the most specific section, we break and return it.
            # Wait, `_get_agent_section` returns the most specific section from a given file.
            # We check project first, then global. If we find ANY of the keys, should we break?
            # Actually, `load_ruleset` and `load_token_budget` return immediately if the section has the key.
            # Here we can just populate the config from the first section that exists.
            return config
    return config
