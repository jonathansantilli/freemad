from __future__ import annotations

from typing import Dict, Type

from .base import Agent

_REGISTRY: Dict[str, Type[Agent]] = {}


def register_agent(agent_type: str, cls: Type[Agent]) -> None:
    key = agent_type.strip().lower()
    if not key:
        raise ValueError("agent_type must be non-empty")
    _REGISTRY[key] = cls


def get_agent_class(agent_type: str) -> Type[Agent]:
    key = agent_type.strip().lower()
    if key not in _REGISTRY:
        raise KeyError(f"unknown agent type: {agent_type}")
    return _REGISTRY[key]


