from __future__ import annotations

import sys
from pathlib import Path
from queue import Queue

from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from freemad.dashboard.app import create_app, DashboardConfig
from freemad.dashboard.live_manager import LiveRunManager, LiveRunState, LiveRunInfo
from freemad.run_events import RunEvent, RunEventKind


def test_websocket_missing_run_returns_1008(tmp_path: Path) -> None:
    cfg = DashboardConfig(transcripts_dir=str(tmp_path))
    client = TestClient(create_app(cfg))
    with client.websocket_connect("/ws/live-runs/missing") as ws:
        data = ws.receive()
        assert data["type"] == "websocket.close"
        assert data["code"] == 1008


def test_websocket_heartbeat_on_idle(tmp_path: Path) -> None:
    cfg = DashboardConfig(transcripts_dir=str(tmp_path))
    app = create_app(cfg)
    mgr: LiveRunManager = app.state.live_manager  # type: ignore[attr-defined]
    run_id = "idle-run"
    q: Queue[RunEvent] = Queue()

    def _raise_empty(block: bool = True, timeout: float | None = None) -> RunEvent:  # noqa: ARG001
        raise __import__("queue").Empty()

    # make get raise queue.Empty immediately to trigger heartbeat
    q.get = _raise_empty  # type: ignore[method-assign,assignment]
    mgr._runs[run_id] = LiveRunState(info=LiveRunInfo(run_id=run_id, completed=False), queue=q)  # type: ignore[attr-defined]

    client = TestClient(app)
    with client.websocket_connect(f"/ws/live-runs/{run_id}") as ws:
        msg = ws.receive()
        assert msg["type"] == "websocket.send"
        assert "heartbeat" in msg.get("text", "")
