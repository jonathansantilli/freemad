from __future__ import annotations

import hashlib
import random
from typing import Dict, List

from .base import Topology
from .info import AllToAllInfo, KReviewersInfo, RingInfo, StarInfo


class AllToAll(Topology):
    def assign_peers(self, agent_ids: List[str]) -> Dict[str, List[str]]:
        peers: Dict[str, List[str]] = {}
        for a in agent_ids:
            peers[a] = [x for x in agent_ids if x != a]
        return peers

    def info(self) -> dict:
        return AllToAllInfo().to_dict()


class KReviewers(Topology):
    def __init__(self, k: int, seed: int):
        self.k = k
        self.seed = seed

    def _seed_for(self, agent_id: str) -> int:
        h = hashlib.sha256(agent_id.encode("utf-8")).digest()
        salt = int.from_bytes(h[:8], "big")
        return (self.seed ^ salt) & ((1 << 64) - 1)

    def assign_peers(self, agent_ids: List[str]) -> Dict[str, List[str]]:
        peers: Dict[str, List[str]] = {}
        for a in agent_ids:
            pool = [x for x in agent_ids if x != a]
            r = random.Random(self._seed_for(a))
            if self.k >= len(pool):
                peers[a] = pool
            else:
                peers[a] = r.sample(pool, self.k)
        return peers

    def info(self) -> dict:
        return KReviewersInfo(k=self.k, seed=self.seed).to_dict()


class Ring(Topology):
    def assign_peers(self, agent_ids: List[str]) -> Dict[str, List[str]]:
        n = len(agent_ids)
        peers: Dict[str, List[str]] = {}
        if n == 1:
            peers[agent_ids[0]] = []
            return peers
        if n == 2:
            # degenerates to all_to_all
            return AllToAll().assign_peers(agent_ids)
        # Each agent reviews the next agent in the ring (single neighbor)
        for i, a in enumerate(agent_ids):
            nxt = agent_ids[(i + 1) % n]
            peers[a] = [nxt]
        return peers

    def info(self) -> dict:
        return RingInfo(neighbors=1).to_dict()


class Star(Topology):
    def __init__(self, hub: str):
        self.hub = hub

    def assign_peers(self, agent_ids: List[str]) -> Dict[str, List[str]]:
        peers: Dict[str, List[str]] = {}
        others = [x for x in agent_ids if x != self.hub]
        for a in agent_ids:
            if a == self.hub:
                peers[a] = others
            else:
                peers[a] = [self.hub]
        return peers

    def info(self) -> dict:
        return StarInfo(hub=self.hub).to_dict()
