from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional

from freemad.types import ArtifactKind, ReviewDecision, TaskEventKind, TaskRole, TaskStage, TaskStatus


@dataclass(frozen=True)
class TaskEvent:
    kind: TaskEventKind
    task_id: str
    ts_ms: int
    stage: Optional[TaskStage] = None
    role: Optional[TaskRole] = None
    status: Optional[TaskStatus] = None
    artifact_id: Optional[str] = None
    artifact_kind: Optional[ArtifactKind] = None
    work_item_id: Optional[str] = None
    review_decision: Optional[ReviewDecision] = None
    message: Optional[str] = None
    error: Optional[str] = None

    def to_dict(self) -> Dict[str, object]:
        data: Dict[str, object] = {
            "kind": self.kind.value,
            "task_id": self.task_id,
            "ts_ms": self.ts_ms,
        }
        if self.stage is not None:
            data["stage"] = self.stage.value
        if self.role is not None:
            data["role"] = self.role.value
        if self.status is not None:
            data["status"] = self.status.value
        if self.artifact_id is not None:
            data["artifact_id"] = self.artifact_id
        if self.artifact_kind is not None:
            data["artifact_kind"] = self.artifact_kind.value
        if self.work_item_id is not None:
            data["work_item_id"] = self.work_item_id
        if self.review_decision is not None:
            data["review_decision"] = self.review_decision.value
        if self.message is not None:
            data["message"] = self.message
        if self.error is not None:
            data["error"] = self.error
        return data


class TaskObserver:
    def on_event(self, event: TaskEvent) -> None:
        raise NotImplementedError


class NullTaskObserver(TaskObserver):
    def on_event(self, event: TaskEvent) -> None:  # pragma: no cover - trivial
        return


class FanOutTaskObserver(TaskObserver):
    def __init__(self, observers: Optional[List[TaskObserver]] = None) -> None:
        self._observers: List[TaskObserver] = list(observers or [])

    def add(self, observer: TaskObserver) -> None:
        self._observers.append(observer)

    def on_event(self, event: TaskEvent) -> None:
        for observer in list(self._observers):
            try:
                observer.on_event(event)
            except Exception:
                continue
