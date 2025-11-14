from __future__ import annotations

from typing import Dict

from freemad import Config, ConfigError

from .base import Agent
from .registry import get_agent_class


class AgentFactory:
    def __init__(self, cfg: Config):
        self.cfg = cfg

    def build_all(self) -> Dict[str, Agent]:
        agents: Dict[str, Agent] = {}
        for a in self.cfg.agents:
            if not a.enabled:
                continue
            try:
                cls = get_agent_class(a.type)
            except KeyError as e:
                raise ConfigError(str(e))
            agents[a.id] = cls(self.cfg, a)
        if not agents:
            raise ConfigError("no enabled agents configured")
        return agents

