from __future__ import annotations

import json
import sqlite3
import threading
import uuid
from dataclasses import replace
from pathlib import Path
from typing import Any, List, Optional, Sequence

from freemad.evolve.models import EvolveEvent, EvolveRunSnapshot, ScoreVector
from freemad.security import Redactor
from freemad.types import EvolveEventKind, EvolveRunStatus


def _redact_payload(value: Any, redactor: Optional["Redactor"]) -> Any:
    """Recursively redact strings on their way into the store.

    Event payloads carry `final_output`, `self_report` and judge stdout/stderr — all
    agent- or worker-authored text that can quote a credential. The logging path has a
    `RedactionFilter`; the store had nothing, so anything redacted from the console was
    still written to SQLite, the report and the dashboard.
    """
    if redactor is None:
        return value
    if isinstance(value, str):
        return redactor.redact(value)
    if isinstance(value, dict):
        return {k: _redact_payload(v, redactor) for k, v in value.items()}
    if isinstance(value, list):
        return [_redact_payload(v, redactor) for v in value]
    return value


class EvolveStore:
    def __init__(
        self,
        store_path: str | Path,
        read_only: bool = False,
        redact_patterns: Optional[Sequence[str]] = None,
    ):
        self._store_path = Path(store_path)
        self._read_only = read_only
        self._redactor: Optional[Redactor] = (
            Redactor(redact_patterns) if redact_patterns else None
        )
        self._lock = threading.RLock()
        if not read_only:
            self._store_path.parent.mkdir(parents=True, exist_ok=True)
        if read_only:
            uri = f"file:{self._store_path.resolve()}?mode=ro"
            self._conn = sqlite3.connect(uri, uri=True, check_same_thread=False)
        else:
            self._conn = sqlite3.connect(str(self._store_path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA busy_timeout=5000")
        if not read_only:
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA synchronous=FULL")
            self._init_db()

    def _init_db(self) -> None:
        with self._lock:
            self._conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS evolve_runs (
                    run_id TEXT PRIMARY KEY,
                    goal TEXT NOT NULL,
                    manifest_hash TEXT NOT NULL,
                    status TEXT NOT NULL,
                    seed_ref TEXT NOT NULL,
                    run_branch TEXT NOT NULL,
                    repo_path TEXT NOT NULL,
                    iteration INTEGER NOT NULL,
                    best_iteration INTEGER,
                    best_sha TEXT,
                    best_score_json TEXT,
                    baseline_score_json TEXT,
                    stop_reason TEXT,
                    error TEXT,
                    interventions_without_new_best INTEGER NOT NULL DEFAULT 0,
                    created_at_ms INTEGER NOT NULL,
                    updated_at_ms INTEGER NOT NULL
                );
                CREATE TABLE IF NOT EXISTS evolve_events (
                    seq INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_id TEXT NOT NULL,
                    ts_ms INTEGER NOT NULL,
                    iteration INTEGER NOT NULL,
                    kind TEXT NOT NULL,
                    payload_json TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_evolve_events_run
                    ON evolve_events (run_id, seq);
                """
            )
            self._conn.commit()

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    def create_run(self, snapshot: EvolveRunSnapshot) -> EvolveRunSnapshot:
        with self._lock:
            now_ms = self._now_ms()
            stored = snapshot
            if snapshot.created_at_ms == 0 or snapshot.updated_at_ms == 0:
                stored = replace(
                    snapshot,
                    created_at_ms=snapshot.created_at_ms or now_ms,
                    updated_at_ms=now_ms,
                )
            self._conn.execute(
                """
                INSERT INTO evolve_runs (
                    run_id, goal, manifest_hash, status, seed_ref, run_branch, repo_path,
                    iteration, best_iteration, best_sha, best_score_json, baseline_score_json,
                    stop_reason, error, interventions_without_new_best, created_at_ms, updated_at_ms
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    stored.run_id,
                    stored.goal,
                    stored.manifest_hash,
                    stored.status.value,
                    stored.seed_ref,
                    stored.run_branch,
                    stored.repo_path,
                    stored.iteration,
                    stored.best_iteration,
                    stored.best_sha,
                    _dump_score(stored.best_score),
                    _dump_score(stored.baseline_score),
                    stored.stop_reason,
                    stored.error,
                    stored.interventions_without_new_best,
                    stored.created_at_ms,
                    stored.updated_at_ms,
                ),
            )
            self._conn.commit()
            return stored

    def update_run(self, snapshot: EvolveRunSnapshot) -> None:
        with self._lock:
            self._conn.execute(
                """
                UPDATE evolve_runs SET
                    goal = ?, manifest_hash = ?, status = ?, seed_ref = ?, run_branch = ?,
                    repo_path = ?, iteration = ?, best_iteration = ?, best_sha = ?,
                    best_score_json = ?, baseline_score_json = ?, stop_reason = ?, error = ?,
                    interventions_without_new_best = ?, updated_at_ms = ?
                WHERE run_id = ?
                """,
                (
                    snapshot.goal,
                    snapshot.manifest_hash,
                    snapshot.status.value,
                    snapshot.seed_ref,
                    snapshot.run_branch,
                    snapshot.repo_path,
                    snapshot.iteration,
                    snapshot.best_iteration,
                    snapshot.best_sha,
                    _dump_score(snapshot.best_score),
                    _dump_score(snapshot.baseline_score),
                    snapshot.stop_reason,
                    snapshot.error,
                    snapshot.interventions_without_new_best,
                    self._now_ms(),
                    snapshot.run_id,
                ),
            )
            self._conn.commit()

    def get_run(self, run_id: str) -> Optional[EvolveRunSnapshot]:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM evolve_runs WHERE run_id = ?", (run_id,)
            ).fetchone()
        return _row_to_snapshot(row) if row is not None else None

    def list_runs(self) -> List[EvolveRunSnapshot]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM evolve_runs ORDER BY created_at_ms ASC"
            ).fetchall()
        return [_row_to_snapshot(row) for row in rows]

    def append_event(
        self,
        run_id: str,
        kind: EvolveEventKind,
        iteration: int,
        payload: dict | None = None,
        ts_ms: int | None = None,
    ) -> EvolveEvent:
        event = EvolveEvent(
            seq=None,
            run_id=run_id,
            ts_ms=ts_ms if ts_ms is not None else self._now_ms(),
            iteration=iteration,
            kind=kind,
            payload=_redact_payload(dict(payload or {}), self._redactor),
        )
        with self._lock:
            cursor = self._conn.execute(
                """
                INSERT INTO evolve_events (run_id, ts_ms, iteration, kind, payload_json)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    event.run_id,
                    event.ts_ms,
                    event.iteration,
                    event.kind.value,
                    json.dumps(event.payload, sort_keys=True),
                ),
            )
            self._conn.commit()
            event = EvolveEvent(
                seq=int(cursor.lastrowid) if cursor.lastrowid is not None else 0,
                run_id=event.run_id,
                ts_ms=event.ts_ms,
                iteration=event.iteration,
                kind=event.kind,
                payload=event.payload,
            )
        return event

    def list_events(self, run_id: str, after_seq: int = 0) -> List[EvolveEvent]:
        with self._lock:
            rows = self._conn.execute(
                """
                SELECT seq, run_id, ts_ms, iteration, kind, payload_json
                FROM evolve_events WHERE run_id = ? AND seq > ? ORDER BY seq ASC
                """,
                (run_id, after_seq),
            ).fetchall()
        return [
            EvolveEvent.from_dict(
                {
                    "seq": row["seq"],
                    "run_id": row["run_id"],
                    "ts_ms": row["ts_ms"],
                    "iteration": row["iteration"],
                    "kind": row["kind"],
                    "payload": json.loads(row["payload_json"]),
                }
            )
            for row in rows
        ]

    def new_run_id(self) -> str:
        return str(uuid.uuid4())

    def _now_ms(self) -> int:
        import time

        return int(time.time() * 1000)


def _dump_score(score: Optional[ScoreVector]) -> Optional[str]:
    if score is None:
        return None
    return json.dumps(score.to_dict(), sort_keys=True)


def _load_score(raw: Optional[str]) -> Optional[ScoreVector]:
    if raw is None:
        return None
    return ScoreVector.from_dict(json.loads(raw))


def _row_to_snapshot(row: sqlite3.Row) -> EvolveRunSnapshot:
    return EvolveRunSnapshot(
        run_id=str(row["run_id"]),
        goal=str(row["goal"]),
        manifest_hash=str(row["manifest_hash"]),
        status=EvolveRunStatus(str(row["status"])),
        seed_ref=str(row["seed_ref"]),
        run_branch=str(row["run_branch"]),
        repo_path=str(row["repo_path"]),
        iteration=int(row["iteration"]),
        best_iteration=(
            int(row["best_iteration"]) if row["best_iteration"] is not None else None
        ),
        best_sha=(str(row["best_sha"]) if row["best_sha"] else None),
        best_score=_load_score(row["best_score_json"]),
        baseline_score=_load_score(row["baseline_score_json"]),
        stop_reason=(str(row["stop_reason"]) if row["stop_reason"] else None),
        error=(str(row["error"]) if row["error"] else None),
        interventions_without_new_best=int(row["interventions_without_new_best"]),
        created_at_ms=int(row["created_at_ms"]),
        updated_at_ms=int(row["updated_at_ms"]),
    )
