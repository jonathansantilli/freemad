from __future__ import annotations

import json
import sqlite3
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Iterable, List, Optional, Sequence

from freemad.task_events import TaskEvent
from freemad.tasks.models import ArtifactRef, StageAttempt, TaskSnapshot, WorkItem
from freemad.types import (
    ArtifactKind,
    ReviewDecision,
    TaskEventKind,
    TaskOutcome,
    TaskRole,
    TaskStage,
    TaskStatus,
    TaskType,
    WorkItemStatus,
)


class TaskStore:
    def __init__(self, store_path: str | Path, artifacts_dir: str | Path):
        self._store_path = Path(store_path)
        self._artifacts_dir = Path(artifacts_dir)
        self._lock = threading.RLock()
        self._artifacts_dir.mkdir(parents=True, exist_ok=True)
        self._store_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self._store_path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._init_db()

    def _init_db(self) -> None:
        with self._lock:
            self._conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS tasks (
                    task_id TEXT PRIMARY KEY,
                    goal TEXT NOT NULL,
                    task_type TEXT NOT NULL,
                    status TEXT NOT NULL,
                    current_stage TEXT NOT NULL,
                    workspace_root TEXT NOT NULL,
                    iteration INTEGER NOT NULL,
                    stage_attempts_json TEXT NOT NULL,
                    error TEXT,
                    created_at_ms INTEGER NOT NULL,
                    updated_at_ms INTEGER NOT NULL
                );
                CREATE TABLE IF NOT EXISTS task_events (
                    seq INTEGER PRIMARY KEY AUTOINCREMENT,
                    task_id TEXT NOT NULL,
                    ts_ms INTEGER NOT NULL,
                    kind TEXT NOT NULL,
                    stage TEXT,
                    role TEXT,
                    status TEXT,
                    artifact_id TEXT,
                    artifact_kind TEXT,
                    work_item_id TEXT,
                    review_decision TEXT,
                    message TEXT,
                    error TEXT
                );
                CREATE TABLE IF NOT EXISTS task_artifacts (
                    artifact_id TEXT PRIMARY KEY,
                    task_id TEXT NOT NULL,
                    stage TEXT NOT NULL,
                    kind TEXT NOT NULL,
                    path TEXT NOT NULL,
                    created_by_agent_id TEXT NOT NULL,
                    created_ts_ms INTEGER NOT NULL,
                    summary TEXT NOT NULL,
                    parent_artifact_ids_json TEXT NOT NULL,
                    role TEXT
                );
                CREATE TABLE IF NOT EXISTS task_work_items (
                    task_id TEXT NOT NULL,
                    work_item_id TEXT NOT NULL,
                    title TEXT NOT NULL,
                    description TEXT NOT NULL,
                    depends_on_json TEXT NOT NULL,
                    write_scope_json TEXT NOT NULL,
                    verification_scope_json TEXT NOT NULL,
                    status TEXT NOT NULL,
                    author_agent_id TEXT,
                    reviewer_agent_id TEXT,
                    arbiter_agent_id TEXT,
                    PRIMARY KEY (task_id, work_item_id)
                );
                """
            )
            self._conn.commit()

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    def create_task(self, goal: str, task_type: TaskType, workspace_root: str) -> TaskSnapshot:
        task = TaskSnapshot(
            task_id=str(uuid.uuid4()),
            goal=goal,
            task_type=task_type,
            status=TaskStatus.PENDING,
            current_stage=TaskStage.INTAKE,
            workspace_root=workspace_root,
        )
        self.update_task(task)
        return task

    def update_task(self, task: TaskSnapshot) -> None:
        with self._lock:
            now_ms = int(time.time() * 1000)
            existing = self._conn.execute(
                "SELECT created_at_ms FROM tasks WHERE task_id = ?",
                (task.task_id,),
            ).fetchone()
            created_at_ms = int(existing["created_at_ms"]) if existing is not None else now_ms
            self._conn.execute(
                """
                INSERT INTO tasks (
                    task_id, goal, task_type, status, current_stage, workspace_root,
                    iteration, stage_attempts_json, error, created_at_ms, updated_at_ms
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(task_id) DO UPDATE SET
                    goal = excluded.goal,
                    task_type = excluded.task_type,
                    status = excluded.status,
                    current_stage = excluded.current_stage,
                    workspace_root = excluded.workspace_root,
                    iteration = excluded.iteration,
                    stage_attempts_json = excluded.stage_attempts_json,
                    error = excluded.error,
                    updated_at_ms = excluded.updated_at_ms
                """,
                (
                    task.task_id,
                    task.goal,
                    task.task_type.value,
                    task.status.value,
                    task.current_stage.value,
                    task.workspace_root,
                    task.iteration,
                    json.dumps([attempt.to_dict() for attempt in task.stage_attempts]),
                    task.error,
                    created_at_ms,
                    now_ms,
                ),
            )
            self._conn.commit()

    def get_task(self, task_id: str) -> Optional[TaskSnapshot]:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM tasks WHERE task_id = ?",
                (task_id,),
            ).fetchone()
        if row is None:
            return None
        return self._row_to_task(row)

    def list_tasks(self) -> List[TaskSnapshot]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM tasks ORDER BY updated_at_ms DESC, created_at_ms DESC",
            ).fetchall()
        return [self._row_to_task(row) for row in rows]

    def append_event(self, event: TaskEvent) -> None:
        with self._lock:
            self._conn.execute(
                """
                INSERT INTO task_events (
                    task_id, ts_ms, kind, stage, role, status, artifact_id,
                    artifact_kind, work_item_id, review_decision, message, error
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    event.task_id,
                    event.ts_ms,
                    event.kind.value,
                    event.stage.value if event.stage is not None else None,
                    event.role.value if event.role is not None else None,
                    event.status.value if event.status is not None else None,
                    event.artifact_id,
                    event.artifact_kind.value if event.artifact_kind is not None else None,
                    event.work_item_id,
                    event.review_decision.value if event.review_decision is not None else None,
                    event.message,
                    event.error,
                ),
            )
            self._conn.commit()

    def list_events(self, task_id: str) -> List[TaskEvent]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM task_events WHERE task_id = ? ORDER BY seq ASC",
                (task_id,),
            ).fetchall()
        return [self._row_to_event(row) for row in rows]

    def save_artifact(
        self,
        task_id: str,
        *,
        kind: ArtifactKind,
        stage: TaskStage,
        content: str,
        created_by_agent_id: str,
        summary: str = "",
        parent_artifact_ids: Sequence[str] = (),
        role: Optional[TaskRole] = None,
    ) -> ArtifactRef:
        artifact_id = str(uuid.uuid4())
        created_ts_ms = int(time.time() * 1000)
        task_dir = self._artifacts_dir / task_id
        task_dir.mkdir(parents=True, exist_ok=True)
        path = task_dir / f"{artifact_id}-{kind.value}.txt"
        path.write_text(content, encoding="utf-8")
        with self._lock:
            self._conn.execute(
                """
                INSERT INTO task_artifacts (
                    artifact_id, task_id, stage, kind, path, created_by_agent_id,
                    created_ts_ms, summary, parent_artifact_ids_json, role
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    artifact_id,
                    task_id,
                    stage.value,
                    kind.value,
                    str(path),
                    created_by_agent_id,
                    created_ts_ms,
                    summary,
                    json.dumps(list(parent_artifact_ids)),
                    role.value if role is not None else None,
                ),
            )
            self._conn.commit()
        return ArtifactRef(
            artifact_id=artifact_id,
            task_id=task_id,
            stage=stage,
            kind=kind,
            path=str(path),
            created_by_agent_id=created_by_agent_id,
            created_ts_ms=created_ts_ms,
            summary=summary,
            parent_artifact_ids=tuple(str(item) for item in parent_artifact_ids),
            role=role,
        )

    def list_artifacts(self, task_id: str) -> List[ArtifactRef]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM task_artifacts WHERE task_id = ? ORDER BY created_ts_ms ASC, artifact_id ASC",
                (task_id,),
            ).fetchall()
        return [self._row_to_artifact(row) for row in rows]

    def save_work_items(self, task_id: str, work_items: Sequence[WorkItem]) -> None:
        with self._lock:
            self._conn.execute("DELETE FROM task_work_items WHERE task_id = ?", (task_id,))
            for work_item in work_items:
                self._conn.execute(
                    """
                    INSERT INTO task_work_items (
                        task_id, work_item_id, title, description, depends_on_json,
                        write_scope_json, verification_scope_json, status,
                        author_agent_id, reviewer_agent_id, arbiter_agent_id
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        task_id,
                        work_item.work_item_id,
                        work_item.title,
                        work_item.description,
                        json.dumps(list(work_item.depends_on)),
                        json.dumps(list(work_item.write_scope)),
                        json.dumps(list(work_item.verification_scope)),
                        work_item.status.value,
                        work_item.author_agent_id,
                        work_item.reviewer_agent_id,
                        work_item.arbiter_agent_id,
                    ),
                )
            self._conn.commit()

    def update_work_item(self, task_id: str, work_item: WorkItem) -> None:
        with self._lock:
            self._conn.execute(
                """
                INSERT INTO task_work_items (
                    task_id, work_item_id, title, description, depends_on_json,
                    write_scope_json, verification_scope_json, status,
                    author_agent_id, reviewer_agent_id, arbiter_agent_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(task_id, work_item_id) DO UPDATE SET
                    title = excluded.title,
                    description = excluded.description,
                    depends_on_json = excluded.depends_on_json,
                    write_scope_json = excluded.write_scope_json,
                    verification_scope_json = excluded.verification_scope_json,
                    status = excluded.status,
                    author_agent_id = excluded.author_agent_id,
                    reviewer_agent_id = excluded.reviewer_agent_id,
                    arbiter_agent_id = excluded.arbiter_agent_id
                """,
                (
                    task_id,
                    work_item.work_item_id,
                    work_item.title,
                    work_item.description,
                    json.dumps(list(work_item.depends_on)),
                    json.dumps(list(work_item.write_scope)),
                    json.dumps(list(work_item.verification_scope)),
                    work_item.status.value,
                    work_item.author_agent_id,
                    work_item.reviewer_agent_id,
                    work_item.arbiter_agent_id,
                ),
            )
            self._conn.commit()

    def list_work_items(self, task_id: str) -> List[WorkItem]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM task_work_items WHERE task_id = ? ORDER BY work_item_id ASC",
                (task_id,),
            ).fetchall()
        return [self._row_to_work_item(row) for row in rows]

    def _row_to_task(self, row: sqlite3.Row) -> TaskSnapshot:
        return TaskSnapshot(
            task_id=str(row["task_id"]),
            goal=str(row["goal"]),
            task_type=TaskType(str(row["task_type"])),
            status=TaskStatus(str(row["status"])),
            current_stage=TaskStage(str(row["current_stage"])),
            workspace_root=str(row["workspace_root"]),
            iteration=int(row["iteration"]),
            stage_attempts=tuple(
                self._stage_attempt_from_dict(item)
                for item in list(json.loads(str(row["stage_attempts_json"]) or "[]") or [])
            ),
            artifacts=tuple(self.list_artifacts(str(row["task_id"]))),
            work_items=tuple(self.list_work_items(str(row["task_id"]))),
            error=(str(row["error"]) if row["error"] is not None else None),
        )

    def _row_to_event(self, row: sqlite3.Row) -> TaskEvent:
        return TaskEvent(
            kind=TaskEventKind(str(row["kind"])),
            task_id=str(row["task_id"]),
            ts_ms=int(row["ts_ms"]),
            stage=(TaskStage(str(row["stage"])) if row["stage"] is not None else None),
            role=(TaskRole(str(row["role"])) if row["role"] is not None else None),
            status=(TaskStatus(str(row["status"])) if row["status"] is not None else None),
            artifact_id=(str(row["artifact_id"]) if row["artifact_id"] is not None else None),
            artifact_kind=(
                ArtifactKind(str(row["artifact_kind"])) if row["artifact_kind"] is not None else None
            ),
            work_item_id=(str(row["work_item_id"]) if row["work_item_id"] is not None else None),
            review_decision=(
                ReviewDecision(str(row["review_decision"]))
                if row["review_decision"] is not None
                else None
            ),
            message=(str(row["message"]) if row["message"] is not None else None),
            error=(str(row["error"]) if row["error"] is not None else None),
        )

    def _row_to_artifact(self, row: sqlite3.Row) -> ArtifactRef:
        return ArtifactRef(
            artifact_id=str(row["artifact_id"]),
            task_id=str(row["task_id"]),
            stage=TaskStage(str(row["stage"])),
            kind=ArtifactKind(str(row["kind"])),
            path=str(row["path"]),
            created_by_agent_id=str(row["created_by_agent_id"]),
            created_ts_ms=int(row["created_ts_ms"]),
            summary=str(row["summary"]),
            parent_artifact_ids=tuple(
                str(item) for item in list(json.loads(str(row["parent_artifact_ids_json"]) or "[]") or [])
            ),
            role=(TaskRole(str(row["role"])) if row["role"] is not None else None),
        )

    def _row_to_work_item(self, row: sqlite3.Row) -> WorkItem:
        return WorkItem(
            work_item_id=str(row["work_item_id"]),
            task_id=str(row["task_id"]),
            title=str(row["title"]),
            description=str(row["description"]),
            depends_on=tuple(str(item) for item in list(json.loads(str(row["depends_on_json"]) or "[]") or [])),
            write_scope=tuple(str(item) for item in list(json.loads(str(row["write_scope_json"]) or "[]") or [])),
            verification_scope=tuple(
                str(item) for item in list(json.loads(str(row["verification_scope_json"]) or "[]") or [])
            ),
            status=WorkItemStatus(str(row["status"])),
            author_agent_id=(str(row["author_agent_id"]) if row["author_agent_id"] is not None else None),
            reviewer_agent_id=(str(row["reviewer_agent_id"]) if row["reviewer_agent_id"] is not None else None),
            arbiter_agent_id=(str(row["arbiter_agent_id"]) if row["arbiter_agent_id"] is not None else None),
        )

    def _stage_attempt_from_dict(self, data: dict[str, Any]) -> StageAttempt:
        return StageAttempt(
            stage=TaskStage(str(data["stage"])),
            attempt_index=int(data["attempt_index"]),
            proposer_agent_id=str(data["proposer_agent_id"]),
            reviewer_agent_id=str(data["reviewer_agent_id"]),
            arbiter_agent_id=(str(data["arbiter_agent_id"]) if data.get("arbiter_agent_id") is not None else None),
            input_artifact_ids=tuple(str(item) for item in list(data.get("input_artifact_ids", []) or [])),
            output_artifact_ids=tuple(str(item) for item in list(data.get("output_artifact_ids", []) or [])),
            outcome=(TaskOutcome(str(data["outcome"])) if data.get("outcome") is not None else None),
            decision_reason=str(data.get("decision_reason", "")),
        )
