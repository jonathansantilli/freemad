from __future__ import annotations

import argparse
import json
import os
import re
import secrets
import threading
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional
import queue

from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.middleware.cors import CORSMiddleware
import difflib
import anyio
import yaml  # type: ignore[import-untyped]

from freemad.config import load_config, ConfigError
from freemad.dashboard.live_manager import LiveRunManager
from freemad.dashboard.task_live_manager import TaskLiveManager
from freemad.dashboard.task_state import apply_task_event, initial_task_snapshot
from freemad.tasks.orchestrator import TaskOrchestrator
from freemad.tasks.store import TaskStore
from freemad.types import RunEventKind, TaskEventKind, TaskStatus, TaskType
from freemad.agents import bootstrap as agent_bootstrap


@dataclass(frozen=True)
class DashboardConfig:
    transcripts_dir: str = "transcripts"
    task_store_path: Path = Path(".freemad/tasks/tasks.db")
    task_artifacts_dir: Path = Path(".freemad/tasks/artifacts")
    override_path: Path | None = None
    override_base: Path | None = None
    enable_csrf: bool = False
    csrf_token: str | None = None
    enable_rate_limit: bool = False
    rate_limit_per_minute: int = 30
    enable_cors: bool = False
    cors_origins: List[str] | None = None


DEFAULT_OVERRIDE_PATH = Path("config_examples/user_override.yaml")
DEFAULT_OVERRIDE_BASE = Path("config_examples/ALL_KEYS.yaml")
TRANSCRIPT_FILE_PATTERN = re.compile(r"^transcript-\d{8}-\d{6}\.json$")


def _parse_ts(name: str) -> Optional[datetime]:
    # transcript-YYYYMMDD-HHMMSS.json
    try:
        stem = Path(name).stem
        ts = stem.replace("transcript-", "")
        return datetime.strptime(ts, "%Y%m%d-%H%M%S")
    except Exception:
        return None


def _ensure_user_override_config(path: Path, base: Path | None) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        return path
    source = base if base and base.exists() else None
    if source is None:
        # Fallback: create an empty shell config
        path.write_text("agents: []\n", encoding="utf-8")
        return path
    path.write_text(source.read_text(encoding="utf-8"), encoding="utf-8")
    return path


def _load_json(p: Path) -> Dict[str, Any]:
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to read {p.name}: {e}")


def _validate_transcript_filename(file: str, transcripts_root: Path) -> Path:
    if not TRANSCRIPT_FILE_PATTERN.match(file):
        raise HTTPException(status_code=400, detail="invalid transcript filename")
    candidate = (transcripts_root / file).resolve()
    if transcripts_root.resolve() not in candidate.parents and transcripts_root.resolve() != candidate:
        raise HTTPException(status_code=400, detail="invalid transcript path")
    return candidate


def _validate_config_path(config_path: str | None, allowed_root: Path) -> str | None:
    if config_path is None:
        return None
    candidate = Path(config_path)
    if candidate.is_absolute():
        raise HTTPException(status_code=400, detail="config_path must be relative")
    normalized = (allowed_root / candidate).resolve()
    if allowed_root.resolve() not in normalized.parents and allowed_root.resolve() != normalized:
        raise HTTPException(status_code=400, detail="config_path must stay within config directory")
    return str(normalized)


def _list_runs(dirpath: Path) -> List[Dict[str, Any]]:
    files = sorted(dirpath.glob("transcript-*.json"))
    runs: List[Dict[str, Any]] = []
    for f in files:
        obj = _load_json(f)
        ts = _parse_ts(f.name)
        ts_display = ts.strftime("%b %d, %Y %H:%M:%S") if ts else None
        runs.append(
            {
                "file": f.name,
                "timestamp": ts.isoformat() if ts else None,
                "display_time": ts_display,
                "final_answer_id": obj.get("final_answer_id"),
                "winning_agents": obj.get("winning_agents", []),
                "rounds": max(0, len(obj.get("transcript", [])) - 1),
                "scores": obj.get("scores", {}),
                "metrics": obj.get("metrics", {}),
            }
        )
    runs.sort(key=lambda x: x.get("timestamp") or "", reverse=True)
    return runs


def _selection_explanation(obj: Dict[str, Any]) -> Dict[str, Any]:
    # Mirrors the tie-break chain: score -> validator_confidence -> lexicographic -> random
    scores: Dict[str, float] = obj.get("scores", {}) or {}
    conf: Dict[str, float] = obj.get("validator_confidence", {}) or obj.get("validation_confidence", {}) or {}
    if not scores:
        return {"reason": "no_scores"}
    max_score = max(scores.values())
    top = [k for k, v in scores.items() if v == max_score]
    reason = [
        {"step": "max_normalized_score", "winners": top, "value": max_score},
    ]
    if len(top) == 1:
        return {"chain": reason}
    max_conf = max(conf.get(k, 0.0) for k in top)
    top2 = [k for k in top if conf.get(k, 0.0) == max_conf]
    reason.append({"step": "max_validator_confidence", "winners": top2, "value": max_conf})
    if len(top2) == 1:
        return {"chain": reason}
    # deterministic lexicographic next
    top2_sorted = sorted(top2)
    reason.append({"step": "lexicographic_answer_id", "winners": [top2_sorted[0]]})
    return {"chain": reason}


def create_app(cfg: DashboardConfig) -> FastAPI:
    # Ensure built-in agents are registered so default configs work
    agent_bootstrap.register_builtin_agents()

    app = FastAPI(title="FREE-MAD Dashboard")
    app.state.csrf_token = cfg.csrf_token or secrets.token_urlsafe(16)
    base_dir = Path(__file__).parent
    templates = Jinja2Templates(directory=str(base_dir / "templates"))
    static_dir = base_dir / "static"
    if static_dir.exists():
        app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")
    static_app_dir = base_dir / "static_app"
    if static_app_dir.exists():
        app.mount("/app", StaticFiles(directory=str(static_app_dir), html=True), name="app")
    if cfg.enable_cors:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=cfg.cors_origins or ["*"],
            allow_methods=["*"],
            allow_headers=["*"],
        )
    # Simple security headers middleware
    @app.middleware("http")
    async def _security_headers(request: Request, call_next):  # type: ignore[override]
        resp = await call_next(request)
        resp.headers.setdefault("X-Content-Type-Options", "nosniff")
        resp.headers.setdefault("X-Frame-Options", "SAMEORIGIN")
        resp.headers.setdefault("Referrer-Policy", "no-referrer")
        resp.headers.setdefault("X-XSS-Protection", "1; mode=block")
        return resp

    transcripts_root = Path(cfg.transcripts_dir)
    transcripts_root.mkdir(parents=True, exist_ok=True)

    live_manager = LiveRunManager()
    app.state.live_manager = live_manager
    task_live_manager = TaskLiveManager()
    app.state.task_live_manager = task_live_manager
    override_path = cfg.override_path or DEFAULT_OVERRIDE_PATH
    override_base = cfg.override_base or DEFAULT_OVERRIDE_BASE
    _ensure_user_override_config(override_path, override_base)
    task_store_path = Path(cfg.task_store_path)
    task_artifacts_dir = Path(cfg.task_artifacts_dir)
    task_store = TaskStore(task_store_path, task_artifacts_dir)

    class _RateLimiter:
        def __init__(self, limit: int) -> None:
            self.limit = max(1, limit)
            self._hits: Dict[str, List[float]] = {}
            self._lock = threading.Lock()

        def allow(self, key: str) -> bool:
            now = time.time()
            cutoff = now - 60
            with self._lock:
                entries = [t for t in self._hits.get(key, []) if t >= cutoff]
                if len(entries) >= self.limit:
                    self._hits[key] = entries
                    return False
                entries.append(now)
                self._hits[key] = entries
                return True

    rate_limiter = _RateLimiter(cfg.rate_limit_per_minute) if cfg.enable_rate_limit else None

    def _require_csrf(request: Request) -> None:
        if not cfg.enable_csrf:
            return
        header = request.headers.get("x-csrf-token") or ""
        cookie = request.cookies.get("csrftoken") or ""
        token = app.state.csrf_token
        if header != cookie and header != token:
            raise HTTPException(status_code=403, detail="csrf validation failed")

    @app.get("/api/config/override", response_class=JSONResponse)
    def api_get_override_config() -> Dict[str, Any]:
        path = _ensure_user_override_config(override_path, override_base)
        try:
            text = path.read_text(encoding="utf-8")
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f"failed to read override config: {exc}")
        return {"path": str(path), "yaml": text}

    @app.post("/api/config/override", response_class=JSONResponse)
    async def api_save_override_config(request: Request) -> Dict[str, Any]:
        _require_csrf(request)
        payload = await request.json()
        content = payload.get("yaml")
        if not isinstance(content, str) or not content.strip():
            raise HTTPException(status_code=400, detail="yaml string is required")
        path = _ensure_user_override_config(override_path, override_base)
        # optimistic write with rollback on validation failure
        previous = path.read_text(encoding="utf-8") if path.exists() else ""
        path.write_text(content, encoding="utf-8")
        try:
            # Validate using the canonical loader to ensure schema correctness
            load_config(path=str(path))
        except Exception as exc:
            # rollback
            path.write_text(previous, encoding="utf-8")
            raise HTTPException(status_code=400, detail=f"config validation failed: {exc}")
        return {"path": str(path), "message": "saved"}

    @app.get("/health", response_class=JSONResponse)
    def health() -> Dict[str, Any]:
        return {"status": "ok", "transcripts_dir": str(transcripts_root.resolve())}

    @app.get("/api/runs", response_class=JSONResponse)
    def api_runs(page: int | None = None, limit: int | None = None) -> Any:
        runs = _list_runs(transcripts_root)
        if page is None and limit is None:
            return runs
        page_num = max(1, page or 1)
        page_size = max(1, min(limit or 50, 500))
        start = (page_num - 1) * page_size
        end = start + page_size
        return {"items": runs[start:end], "page": page_num, "limit": page_size, "total": len(runs)}

    @app.get("/api/runs/{file}", response_class=JSONResponse)
    def api_run_detail(file: str) -> Dict[str, Any]:
        p = _validate_transcript_filename(file, transcripts_root)
        if not p.exists():
            raise HTTPException(status_code=404, detail="run not found")
        obj = _load_json(p)
        # Backfill winning_agents if missing (older transcripts)
        if not obj.get("winning_agents"):
            fid = obj.get("final_answer_id")
            if fid and obj.get("holders_history"):
                holders = obj.get("holders_history", {})
                # Choose latest round holders if available
                latest = sorted(holders.keys())[-1] if holders else None
                if latest is not None:
                    obj["winning_agents"] = holders.get(latest, [])
        if not obj.get("winning_agents"):
            obj["winning_agents"] = []
        obj["selection_explanation"] = _selection_explanation(obj)
        return obj

    @app.delete("/api/runs/{file}", response_class=JSONResponse)
    def api_run_delete(file: str) -> Dict[str, str]:
        p = _validate_transcript_filename(file, transcripts_root)
        if not p.exists():
            raise HTTPException(status_code=404, detail="run not found")
        p.unlink()
        return {"message": "deleted", "file": file}

    @app.post("/api/live-runs", response_class=JSONResponse)
    async def api_live_run_start(request: Request) -> Dict[str, Any]:
        _require_csrf(request)
        if rate_limiter is not None:
            key = request.client.host if request.client else "unknown"
            if not rate_limiter.allow(key):
                raise HTTPException(status_code=429, detail="too many live run requests")
        payload = await request.json()
        requirement = str(payload.get("requirement", "")).strip()
        if not requirement:
            raise HTTPException(status_code=400, detail="requirement is required")
        config_path = payload.get("config_path")
        max_rounds_val = payload.get("max_rounds", 1)
        try:
            max_rounds = int(max_rounds_val)
        except (TypeError, ValueError):
            raise HTTPException(status_code=400, detail="max_rounds must be an integer")
        overrides = payload.get("overrides")
        if overrides is not None and not isinstance(overrides, dict):
            raise HTTPException(status_code=400, detail="overrides must be an object if provided")
        allowed_config_root = Path.cwd()
        try:
            # If no config/overrides provided, default to mock agents for a smooth dashboard experience.
            default_path = config_path
            if not default_path and not overrides:
                default_path = "config_examples/mock_agents.yaml"
            cfg_path = _validate_config_path(default_path, allowed_config_root) if default_path else None
            cfg_obj = load_config(path=cfg_path, overrides=overrides)
        except ConfigError as e:
            raise HTTPException(status_code=400, detail=f"config error: {e}")
        run_id = live_manager.start_run(cfg_obj, requirement, max_rounds=max_rounds)
        return {"run_id": run_id}

    @app.websocket("/ws/live-runs/{run_id}")
    async def ws_live_run(ws: WebSocket, run_id: str) -> None:
        await ws.accept()
        q = live_manager.get_queue(run_id)
        if q is None:
            await ws.close(code=1008)
            return
        try:
            while True:
                try:
                    event = await anyio.to_thread.run_sync(lambda: q.get(timeout=1.0))
                    await ws.send_json({"event": event.to_dict()})
                    if event.kind in (
                        RunEventKind.RUN_COMPLETED,
                        RunEventKind.RUN_FAILED,
                        RunEventKind.RUN_BUDGET_EXCEEDED,
                    ):
                        break
                except queue.Empty:
                    await ws.send_json({"event": {"kind": "heartbeat"}})
        except WebSocketDisconnect:
            return
        finally:
            await ws.close()

    def _task_payload(task_id: str) -> Dict[str, Any]:
        task = task_store.get_task(task_id)
        if task is None:
            raise HTTPException(status_code=404, detail="task not found")
        events = task_store.list_events(task_id)
        snapshot = initial_task_snapshot(task_id)
        for event in events:
            snapshot = apply_task_event(snapshot, event)
        return {
            **task.to_dict(),
            "artifacts": [artifact.to_dict() for artifact in task_store.list_artifacts(task_id)],
            "work_items": [item.to_dict() for item in task_store.list_work_items(task_id)],
            "events": [event.to_dict() for event in events],
            "snapshot": {
                "task_id": snapshot.task_id,
                "status": snapshot.status.value,
                "current_stage": snapshot.current_stage.value if snapshot.current_stage is not None else None,
                "artifact_counts": dict(snapshot.artifact_counts),
                "completed": snapshot.completed,
                "error": snapshot.error,
            },
        }

    @app.get("/api/tasks", response_class=JSONResponse)
    def api_tasks() -> List[Dict[str, Any]]:
        return [task.to_dict() for task in task_store.list_tasks()]

    @app.get("/api/tasks/{task_id}", response_class=JSONResponse)
    def api_task_detail(task_id: str) -> Dict[str, Any]:
        return _task_payload(task_id)

    @app.post("/api/tasks", response_class=JSONResponse)
    async def api_task_start(request: Request) -> Dict[str, Any]:
        _require_csrf(request)
        payload = await request.json()
        goal = str(payload.get("goal", "")).strip()
        if not goal:
            raise HTTPException(status_code=400, detail="goal is required")
        task_type_raw = str(payload.get("task_type", TaskType.PLAN.value)).strip().lower()
        try:
            task_type = TaskType(task_type_raw)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=f"invalid task_type: {task_type_raw}") from exc
        workspace_root = str(payload.get("workspace_root", ".")).strip() or "."
        config_path = payload.get("config_path")
        overrides = payload.get("overrides")
        if overrides is not None and not isinstance(overrides, dict):
            raise HTTPException(status_code=400, detail="overrides must be an object if provided")
        merged_overrides = dict(overrides or {})
        task_override = dict(merged_overrides.get("task", {}) or {})
        task_override.setdefault("store_path", str(task_store_path))
        task_override.setdefault("artifacts_dir", str(task_artifacts_dir))
        merged_overrides["task"] = task_override
        try:
            cfg_obj = load_config(path=config_path if config_path else None, overrides=merged_overrides)
        except ConfigError as exc:
            raise HTTPException(status_code=400, detail=f"config error: {exc}") from exc
        task_id = task_live_manager.start_task(
            cfg_obj,
            goal=goal,
            task_type=task_type,
            workspace_root=workspace_root,
        )
        return {"task_id": task_id}

    @app.websocket("/ws/tasks/{task_id}")
    async def ws_task(ws: WebSocket, task_id: str) -> None:
        await ws.accept()
        try:
            sent = 0
            terminal_statuses = {
                TaskStatus.COMPLETED,
                TaskStatus.FAILED,
                TaskStatus.PAUSED,
                TaskStatus.WAITING_FOR_HUMAN,
            }
            while True:
                events = task_store.list_events(task_id)
                task = task_store.get_task(task_id)
                if not events and task is None and not task_live_manager.has_task(task_id):
                    await ws.close(code=1008)
                    return
                while sent < len(events):
                    event = events[sent]
                    sent += 1
                    await ws.send_json({"event": event.to_dict()})
                    if event.kind in (
                        TaskEventKind.TASK_COMPLETED,
                        TaskEventKind.TASK_FAILED,
                        TaskEventKind.TASK_PAUSED,
                    ):
                        return
                if task is not None and task.status in terminal_statuses:
                    return
                if task_live_manager.has_task(task_id) and not task_live_manager.is_completed(task_id):
                    await anyio.sleep(0.05)
                    continue
                await anyio.sleep(0.05)
        except WebSocketDisconnect:
            return
        finally:
            await ws.close()

    @app.get("/", response_class=HTMLResponse)
    def index(request: Request) -> HTMLResponse:
        runs = _list_runs(transcripts_root)
        resp = templates.TemplateResponse(
            request=request,
            name="index.html",
            context={"runs": runs},
        )
        if cfg.enable_csrf:
            resp.set_cookie("csrftoken", app.state.csrf_token, httponly=False, samesite="lax")
        return resp

    @app.get("/tasks", response_class=HTMLResponse)
    def tasks_index(request: Request) -> HTMLResponse:
        resp = templates.TemplateResponse(
            request=request,
            name="tasks.html",
            context={"tasks": [task.to_dict() for task in task_store.list_tasks()]},
        )
        if cfg.enable_csrf:
            resp.set_cookie("csrftoken", app.state.csrf_token, httponly=False, samesite="lax")
        return resp

    @app.get("/tasks/{task_id}", response_class=HTMLResponse)
    def task_detail(request: Request, task_id: str) -> HTMLResponse:
        payload = _task_payload(task_id)
        resp = templates.TemplateResponse(
            request=request,
            name="task.html",
            context={"task": payload},
        )
        if cfg.enable_csrf:
            resp.set_cookie("csrftoken", app.state.csrf_token, httponly=False, samesite="lax")
        return resp

    @app.get("/runs/{file}", response_class=HTMLResponse)
    def run_detail(request: Request, file: str) -> HTMLResponse:
        p = _validate_transcript_filename(file, transcripts_root)
        if not p.exists():
            raise HTTPException(status_code=404, detail="run not found")
        obj = _load_json(p)
        # augment for UI
        obj["_file"] = file
        ts = _parse_ts(file)
        obj["_timestamp"] = ts.isoformat() if ts else None
        obj["selection_explanation"] = _selection_explanation(obj)
        # Build per-agent debate timeline with previous solutions for diffs
        timeline: Dict[str, List[Dict[str, Any]]] = {}
        prev_solution: Dict[str, str] = {}
        for r in obj.get("transcript", []):
            round_idx = r.get("round")
            rtype = r.get("type")
            agents = r.get("agents", {}) or {}
            for aid, rec in agents.items():
                resp = rec.get("response", {}) or {}
                sol = resp.get("solution", "") or ""
                reason = resp.get("reasoning", "") or ""
                decision = resp.get("decision", "")
                changed = resp.get("changed", False)
                ans_id = resp.get("answer_id")
                prev = prev_solution.get(aid, "")
                diff = ""
                if changed and prev and sol and prev != sol:
                    diff_lines = difflib.unified_diff(
                        prev.splitlines(), sol.splitlines(), fromfile="prev", tofile="new", lineterm=""
                    )
                    # limit diff length for safety
                    diff = "\n".join(list(diff_lines)[:200])
                entry = {
                    "round": round_idx,
                    "type": rtype,
                    "decision": decision,
                    "changed": changed,
                    "reasoning": reason,
                    "answer_id": ans_id,
                    "peers_seen": rec.get("peers_seen_count", 0),
                    "peers_assigned": rec.get("peers_assigned_count", 0),
                    "solution": sol,
                    "prev_solution": prev,
                    "diff": diff,
                }
                timeline.setdefault(aid, []).append(entry)
                prev_solution[aid] = sol
        obj["timeline"] = timeline
        # Build groups by round for collapsible UI
        round_groups: List[Dict[str, Any]] = []
        for r in obj.get("transcript", []):
            r_idx = r.get("round")
            r_type = r.get("type")
            events: List[Dict[str, Any]] = []
            for aid, evs in timeline.items():
                e = next((x for x in evs if x.get("round") == r_idx), None)
                if e is not None:
                    events.append({"agent_id": aid, **e})
            changed_count = sum(1 for e in events if e.get("changed"))
            round_groups.append({"round": r_idx, "type": r_type, "events": events, "changed_count": changed_count})
        obj["round_groups"] = round_groups
        # score history for winner
        fid = obj.get("final_answer_id")
        if fid and obj.get("score_explainers"):
            obj["winner_score_history"] = obj["score_explainers"].get(fid, [])
        resp = templates.TemplateResponse(
            request=request,
            name="run.html",
            context={"run": obj},
        )
        if cfg.enable_csrf:
            resp.set_cookie("csrftoken", app.state.csrf_token, httponly=False, samesite="lax")
        return resp

    return app


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="FREE-MAD Dashboard")
    ap.add_argument("--dir", default="transcripts", help="Transcripts directory")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", default=8000, type=int)
    args = ap.parse_args(argv)

    cfg = DashboardConfig(transcripts_dir=args.dir)
    app = create_app(cfg)

    # Run uvicorn programmatically
    import uvicorn

    uvicorn.run(app, host=args.host, port=args.port)
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
