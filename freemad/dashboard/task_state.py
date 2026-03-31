from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Optional

from freemad.task_events import TaskEvent
from freemad.types import TaskEventKind, TaskStage, TaskStatus


@dataclass(frozen=True)
class TaskSnapshot:
    task_id: str
    status: TaskStatus = TaskStatus.PENDING
    current_stage: Optional[TaskStage] = None
    artifact_counts: Dict[str, int] = field(default_factory=dict)
    completed: bool = False
    error: Optional[str] = None


def initial_task_snapshot(task_id: str) -> TaskSnapshot:
    return TaskSnapshot(task_id=task_id)


def apply_task_event(snapshot: TaskSnapshot, event: TaskEvent) -> TaskSnapshot:
    if snapshot.task_id != event.task_id:
        return snapshot
    if event.kind == TaskEventKind.STAGE_STARTED and event.stage is not None:
        return TaskSnapshot(
            task_id=snapshot.task_id,
            status=snapshot.status,
            current_stage=event.stage,
            artifact_counts=dict(snapshot.artifact_counts),
            completed=snapshot.completed,
            error=snapshot.error,
        )
    if event.kind == TaskEventKind.ARTIFACT_CREATED and event.artifact_kind is not None:
        counts = dict(snapshot.artifact_counts)
        key = event.artifact_kind.value
        counts[key] = counts.get(key, 0) + 1
        return TaskSnapshot(
            task_id=snapshot.task_id,
            status=snapshot.status,
            current_stage=snapshot.current_stage,
            artifact_counts=counts,
            completed=snapshot.completed,
            error=snapshot.error,
        )
    if event.kind in (TaskEventKind.TASK_STARTED, TaskEventKind.TASK_COMPLETED, TaskEventKind.TASK_PAUSED, TaskEventKind.TASK_FAILED):
        status = event.status or snapshot.status
        completed = event.kind in (TaskEventKind.TASK_COMPLETED, TaskEventKind.TASK_PAUSED, TaskEventKind.TASK_FAILED)
        return TaskSnapshot(
            task_id=snapshot.task_id,
            status=status,
            current_stage=snapshot.current_stage,
            artifact_counts=dict(snapshot.artifact_counts),
            completed=completed,
            error=event.error if event.error is not None else snapshot.error,
        )
    return snapshot
