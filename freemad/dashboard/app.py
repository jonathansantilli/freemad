from __future__ import annotations

import argparse
import json
import os
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
import difflib


@dataclass(frozen=True)
class DashboardConfig:
    transcripts_dir: str = "transcripts"


def _parse_ts(name: str) -> Optional[datetime]:
    # transcript-YYYYMMDD-HHMMSS.json
    try:
        stem = Path(name).stem
        ts = stem.replace("transcript-", "")
        return datetime.strptime(ts, "%Y%m%d-%H%M%S")
    except Exception:
        return None


def _load_json(p: Path) -> Dict[str, Any]:
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to read {p.name}: {e}")


def _list_runs(dirpath: Path) -> List[Dict[str, Any]]:
    files = sorted(dirpath.glob("transcript-*.json"))
    runs: List[Dict[str, Any]] = []
    for f in files:
        obj = _load_json(f)
        ts = _parse_ts(f.name)
        runs.append(
            {
                "file": f.name,
                "timestamp": ts.isoformat() if ts else None,
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
    app = FastAPI(title="FREE-MAD Dashboard")
    base_dir = Path(__file__).parent
    templates = Jinja2Templates(directory=str(base_dir / "templates"))
    static_dir = base_dir / "static"
    if static_dir.exists():
        app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

    transcripts_root = Path(cfg.transcripts_dir)
    transcripts_root.mkdir(parents=True, exist_ok=True)

    @app.get("/health", response_class=JSONResponse)
    def health() -> Dict[str, Any]:
        return {"status": "ok", "transcripts_dir": str(transcripts_root.resolve())}

    @app.get("/api/runs", response_class=JSONResponse)
    def api_runs() -> List[Dict[str, Any]]:
        return _list_runs(transcripts_root)

    @app.get("/api/runs/{file}", response_class=JSONResponse)
    def api_run_detail(file: str) -> Dict[str, Any]:
        p = transcripts_root / file
        if not p.exists():
            raise HTTPException(status_code=404, detail="run not found")
        obj = _load_json(p)
        obj["selection_explanation"] = _selection_explanation(obj)
        return obj

    @app.get("/", response_class=HTMLResponse)
    def index(request: Request) -> HTMLResponse:
        runs = _list_runs(transcripts_root)
        return templates.TemplateResponse("index.html", {"request": request, "runs": runs})

    @app.get("/runs/{file}", response_class=HTMLResponse)
    def run_detail(request: Request, file: str) -> HTMLResponse:
        p = transcripts_root / file
        if not p.exists():
            raise HTTPException(status_code=404, detail="run not found")
        obj = _load_json(p)
        # augment for UI
        obj["_file"] = file
        obj["_timestamp"] = _parse_ts(file).isoformat() if _parse_ts(file) else None
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
        return templates.TemplateResponse("run.html", {"request": request, "run": obj})

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
