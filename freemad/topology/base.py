from __future__ import annotations

import abc
from typing import Dict, List


class Topology(abc.ABC):
    @abc.abstractmethod
    def assign_peers(self, agent_ids: List[str]) -> Dict[str, List[str]]:
        """Return mapping agent_id -> list of peer agent_ids."""
        ...

    @abc.abstractmethod
    def info(self) -> dict:
        """Return topology metadata for transcripts/logging."""
        ...

