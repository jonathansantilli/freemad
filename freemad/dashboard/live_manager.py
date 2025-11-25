from __future__ import annotations

import threading
import uuid
from dataclasses import dataclass
from queue import Queue
from typing import Callable, Dict, Optional

from freemad import Config, Orchestrator
from freemad.run_events import RunEvent, RunObserver
from freemad.types import RunEventKind
from freemad.utils.transcript import save_transcript


@dataclass(frozen=True)
class LiveRunInfo:
    run_id: str
    completed: bool = False


@dataclass(frozen=True)
class LiveRunState:
    info: LiveRunInfo
    queue: Queue[RunEvent]


class _QueueObserver(RunObserver):
    def __init__(self, q: Queue[RunEvent], on_terminal: Callable[[str], None]) -> None:
        self._q = q
        self._on_terminal = on_terminal

    def on_event(self, event: RunEvent) -> None:
        # Queue is thread-safe; put events for streaming consumers.
        self._q.put(event)
        if event.kind in (
            RunEventKind.RUN_COMPLETED,
            RunEventKind.RUN_FAILED,
            RunEventKind.RUN_BUDGET_EXCEEDED,
        ):
            self._on_terminal(event.run_id)


class LiveRunManager:
    """In-process manager for live runs and their event queues.

    This is intentionally minimal and backend-agnostic; FastAPI routes
    can use it to start runs and bridge queues into WebSocket streams.
    """

    def __init__(self) -> None:
        self._runs: Dict[str, LiveRunState] = {}
        self._lock = threading.Lock()

    def _mark_completed(self, run_id: str) -> None:
        with self._lock:
            state = self._runs.get(run_id)
            if state is not None:
                self._runs[run_id] = LiveRunState(
                    info=LiveRunInfo(run_id=state.info.run_id, completed=True),
                    queue=state.queue,
                )

    def start_run(self, cfg: Config, requirement: str, max_rounds: int = 1) -> str:
        run_id = str(uuid.uuid4())
        q: Queue[RunEvent] = Queue()
        observer = _QueueObserver(q, self._mark_completed)
        orch = Orchestrator(cfg, observer=observer)

        def _worker() -> None:
            try:
                result = orch.run(requirement, max_rounds=max_rounds, run_id=run_id)
                # Persist transcript for dashboard runs, mirroring CLI behavior.
                if cfg.output.save_transcript:
                    # Use the configured transcript_dir/format from the config.
                    save_transcript(
                        result,
                        cfg.output.format,
                        cfg.output.transcript_dir,
                    )
            except Exception as e:
                # Emit a synthetic failure event so clients see termination.
                q.put(
                    RunEvent(
                        kind=RunEventKind.RUN_FAILED,
                        run_id=run_id,
                        ts_ms=0,
                        error=str(e),
                    )
                )
            finally:
                self._mark_completed(run_id)

        t = threading.Thread(target=_worker, name=f"freemad-run-{run_id}", daemon=True)
        with self._lock:
            self._runs[run_id] = LiveRunState(info=LiveRunInfo(run_id=run_id, completed=False), queue=q)
        t.start()
        return run_id

    def get_queue(self, run_id: str) -> Optional[Queue[RunEvent]]:
        with self._lock:
            state = self._runs.get(run_id)
            return state.queue if state is not None else None

    def is_completed(self, run_id: str) -> bool:
        with self._lock:
            state = self._runs.get(run_id)
            return bool(state and state.info.completed)
