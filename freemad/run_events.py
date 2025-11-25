from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional

from freemad.types import Decision, RoundType, RunEventKind


@dataclass(frozen=True)
class RunEvent:
    kind: RunEventKind
    run_id: str
    ts_ms: int
    round_index: Optional[int] = None
    round_type: Optional[RoundType] = None
    agent_id: Optional[str] = None
    answer_id: Optional[str] = None
    decision: Optional[Decision] = None
    changed: Optional[bool] = None
    scores: dict[str, float] = field(default_factory=dict)
    holders: dict[str, list[str]] = field(default_factory=dict)
    winning_agents: list[str] = field(default_factory=list)
    final_answer_id: Optional[str] = None
    selection_chain: Optional[list[dict[str, object]]] = None
    error: Optional[str] = None

    def to_dict(self) -> Dict[str, object]:
        data: Dict[str, object] = {
            "kind": self.kind.value,
            "run_id": self.run_id,
            "ts_ms": self.ts_ms,
        }
        if self.round_index is not None:
            data["round_index"] = self.round_index
        if self.round_type is not None:
            data["round_type"] = self.round_type.value
        if self.agent_id is not None:
            data["agent_id"] = self.agent_id
        if self.answer_id is not None:
            data["answer_id"] = self.answer_id
        if self.decision is not None:
            data["decision"] = self.decision.value
        if self.changed is not None:
            data["changed"] = self.changed
        if self.scores:
            data["scores"] = dict(self.scores)
        if self.holders:
            data["holders"] = {k: list(v) for k, v in self.holders.items()}
        if self.winning_agents:
            data["winning_agents"] = list(self.winning_agents)
        if self.final_answer_id is not None:
            data["final_answer_id"] = self.final_answer_id
        if self.selection_chain is not None:
            data["selection_chain"] = list(self.selection_chain)
        if self.error is not None:
            data["error"] = self.error
        return data


class RunObserver:
    def on_event(self, event: RunEvent) -> None:
        raise NotImplementedError


class NullObserver(RunObserver):
    def on_event(self, event: RunEvent) -> None:  # pragma: no cover - trivial
        return


class FanOutObserver(RunObserver):
    def __init__(self, observers: Optional[List[RunObserver]] = None) -> None:
        self._observers: List[RunObserver] = list(observers or [])

    def add(self, observer: RunObserver) -> None:
        self._observers.append(observer)

    def on_event(self, event: RunEvent) -> None:
        for obs in list(self._observers):
            try:
                obs.on_event(event)
            except Exception:
                # Observers must be best-effort; errors are ignored.
                continue
