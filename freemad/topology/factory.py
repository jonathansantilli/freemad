from __future__ import annotations

from freemad import Config, ConfigError

from .base import Topology
from .impl import AllToAll, KReviewers, Ring, Star


def build_topology(cfg: Config) -> Topology:
    t = cfg.topology.type
    if t == "all_to_all":
        return AllToAll()
    if t == "k_reviewers":
        if cfg.topology.k is None:
            raise ConfigError("topology.k required for k_reviewers")
        return KReviewers(k=cfg.topology.k, seed=cfg.topology.seed)
    if t == "ring":
        return Ring()
    if t == "star":
        if not cfg.topology.hub_agent:
            raise ConfigError("topology.hub_agent required for star")
        return Star(hub=cfg.topology.hub_agent)
    raise ConfigError(f"unknown topology: {t}")

