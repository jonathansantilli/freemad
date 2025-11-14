from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Dict


@dataclass(frozen=True)
class TopologyInfo:
    type: str
    def to_dict(self) -> Dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class AllToAllInfo(TopologyInfo):
    type: str = "all_to_all"


@dataclass(frozen=True)
class KReviewersInfo(TopologyInfo):
    k: int = 1
    seed: int = 0
    type: str = "k_reviewers"


@dataclass(frozen=True)
class RingInfo(TopologyInfo):
    neighbors: int = 1
    type: str = "ring"


@dataclass(frozen=True)
class StarInfo(TopologyInfo):
    hub: str = ""
    type: str = "star"

