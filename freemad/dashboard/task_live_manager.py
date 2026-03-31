from __future__ import annotations

import threading
from dataclasses import dataclass
from typing import Dict

from freemad.config import Config
from freemad.tasks.orchestrator import TaskOrchestrator
from freemad.types import TaskType


@dataclass(frozen=True)
class LiveTaskInfo:
    task_id: str
    completed: bool = False


class TaskLiveManager:
    def __init__(self) -> None:
        self._tasks: Dict[str, LiveTaskInfo] = {}
        self._lock = threading.Lock()

    def start_task(self, cfg: Config, *, goal: str, task_type: TaskType, workspace_root: str) -> str:
        orch = TaskOrchestrator(cfg)
        task = orch.create_task(goal=goal, task_type=task_type, workspace_root=workspace_root)

        def _worker() -> None:
            try:
                orch.run(task.task_id)
            finally:
                self._mark_completed(task.task_id)

        thread = threading.Thread(target=_worker, name=f"freemad-task-{task.task_id}", daemon=True)
        with self._lock:
            self._tasks[task.task_id] = LiveTaskInfo(task_id=task.task_id, completed=False)
        thread.start()
        return task.task_id

    def has_task(self, task_id: str) -> bool:
        with self._lock:
            return task_id in self._tasks

    def is_completed(self, task_id: str) -> bool:
        with self._lock:
            info = self._tasks.get(task_id)
            return bool(info and info.completed)

    def _mark_completed(self, task_id: str) -> None:
        with self._lock:
            info = self._tasks.get(task_id)
            if info is not None:
                self._tasks[task_id] = LiveTaskInfo(task_id=task_id, completed=True)
