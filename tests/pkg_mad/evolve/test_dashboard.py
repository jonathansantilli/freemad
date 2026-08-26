from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from freemad.dashboard.app import DashboardConfig, create_app
from freemad.evolve.models import EvolveRunSnapshot, ScoreVector
from freemad.evolve.store import EvolveStore
from freemad.types import EvolveEventKind, EvolveRunStatus


def _seed_run(db_path: Path) -> str:
    store = EvolveStore(db_path)
    snapshot = store.create_run(
        EvolveRunSnapshot(
            run_id="dash-run",
            goal="make it fast",
            manifest_hash="h" * 64,
            status=EvolveRunStatus.COMPLETED,
            seed_ref="HEAD",
            run_branch="evolve/dash-run",
            repo_path="/tmp",
            iteration=2,
            best_iteration=1,
            best_sha="abc123",
            best_score=ScoreVector(components={"ops_per_sec": 9000.0}),
            baseline_score=ScoreVector(components={"ops_per_sec": 100.0}),
            stop_reason="target_reached",
        )
    )
    store.append_event("dash-run", EvolveEventKind.RUN_CREATED, 0)
    verdict = {"score": {"ops_per_sec": 100.0}, "gate_passed": True}
    store.append_event(
        "dash-run", EvolveEventKind.BASELINE_JUDGED, 0, {"verdict": verdict}
    )
    store.append_event(
        "dash-run",
        EvolveEventKind.CANDIDATE_COMMITTED,
        1,
        {
            "sha": "abc123def4567890",
            "tag": "evolve/dash-run/v1",
            "score": {"ops_per_sec": 9000.0},
        },
    )
    store.append_event(
        "dash-run", EvolveEventKind.SUPERVISOR_TRIGGERED, 3, {"cause": "stall"}
    )
    assert snapshot.run_id == "dash-run"
    store.close()
    return "dash-run"


class _EvolveDashboard:
    def __init__(self, tmp_path: Path):
        self.db = tmp_path / "evolve.db"
        self.client = TestClient(create_app(DashboardConfig(evolve_store_path=self.db)))


def test_evolve_detail_returns_trajectory(tmp_path: Path) -> None:
    dash = _EvolveDashboard(tmp_path)
    run_id = _seed_run(dash.db)

    resp = dash.client.get(f"/api/evolve/{run_id}")
    assert resp.status_code == 200
    payload = resp.json()
    assert payload["goal"] == "make it fast"
    assert payload["baseline_score"] == {"ops_per_sec": 100.0}
    assert len(payload["points"]) == 1
    point = payload["points"][0]
    assert point["iteration"] == 1
    # Each accepted version reports its OWN score. The old "cumulative_best" key
    # merged the last-accepted value per component, which for a regressed component
    # was neither a maximum nor a minimum — a label the data did not support.
    assert point["score"]["ops_per_sec"] == 9000.0
    assert "cumulative_best" not in point
    assert payload["interventions"][0]["cause"] == "stall"


def test_evolve_trajectory_page_renders(tmp_path: Path) -> None:
    dash = _EvolveDashboard(tmp_path)
    run_id = _seed_run(dash.db)

    resp = dash.client.get(f"/evolve/{run_id}")
    assert resp.status_code == 200
    body = resp.text
    assert "make it fast" in body
    assert "Score at each accepted version" in body


def test_evolve_unknown_run_is_404(tmp_path: Path) -> None:
    dash = _EvolveDashboard(tmp_path)
    resp = dash.client.get("/api/evolve/nope")
    assert resp.status_code == 404
