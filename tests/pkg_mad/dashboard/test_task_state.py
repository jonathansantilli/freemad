from __future__ import annotations

from freemad.dashboard.task_state import apply_task_event, initial_task_snapshot
from freemad.task_events import TaskEvent
from freemad.types import ArtifactKind, TaskEventKind, TaskStage, TaskStatus


def test_task_state_reduces_stage_artifact_and_terminal_events() -> None:
    task_id = "task-1"
    snapshot = initial_task_snapshot(task_id)

    snapshot = apply_task_event(
        snapshot,
        TaskEvent(
            kind=TaskEventKind.STAGE_STARTED,
            task_id=task_id,
            ts_ms=1,
            stage=TaskStage.RESEARCH,
        ),
    )
    assert snapshot.current_stage == TaskStage.RESEARCH

    snapshot = apply_task_event(
        snapshot,
        TaskEvent(
            kind=TaskEventKind.ARTIFACT_CREATED,
            task_id=task_id,
            ts_ms=2,
            stage=TaskStage.RESEARCH,
            artifact_kind=ArtifactKind.RESEARCH_BUNDLE,
        ),
    )
    assert snapshot.artifact_counts[ArtifactKind.RESEARCH_BUNDLE.value] == 1

    snapshot = apply_task_event(
        snapshot,
        TaskEvent(
            kind=TaskEventKind.TASK_COMPLETED,
            task_id=task_id,
            ts_ms=3,
            status=TaskStatus.COMPLETED,
        ),
    )
    assert snapshot.status == TaskStatus.COMPLETED
    assert snapshot.completed is True

