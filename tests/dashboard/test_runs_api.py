from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from freemad.dashboard.app import create_app, DashboardConfig


def _make_app(tmpdir: Path) -> TestClient:
    cfg = DashboardConfig(transcripts_dir=str(tmpdir))
    return TestClient(create_app(cfg))


def _write_transcript(tmpdir: Path, name: str) -> None:
    data = {
        "final_answer_id": "a1",
        "winning_agents": ["a"],
        "scores": {"a1": 1.0},
        "transcript": [{"round": 0, "agents": {}}],
    }
    (tmpdir / name).write_text(json.dumps(data), encoding="utf-8")


def test_api_run_detail_rejects_bad_filename(tmp_path: Path) -> None:
    client = _make_app(tmp_path)
    resp = client.get("/api/runs/evil.json")
    assert resp.status_code == 400


def test_api_run_detail_missing(tmp_path: Path) -> None:
    client = _make_app(tmp_path)
    resp = client.get("/api/runs/transcript-19990101-000000.json")
    assert resp.status_code == 404


def test_api_runs_delete_removes_file(tmp_path: Path) -> None:
    name = "transcript-20240101-120000.json"
    _write_transcript(tmp_path, name)
    client = _make_app(tmp_path)
    assert (tmp_path / name).exists()
    resp = client.delete(f"/api/runs/{name}")
    assert resp.status_code == 200
    assert not (tmp_path / name).exists()
    resp = client.delete(f"/api/runs/{name}")
    assert resp.status_code == 404


def test_api_runs_paginates(tmp_path: Path) -> None:
    for i in range(3):
        _write_transcript(tmp_path, f"transcript-20240101-12000{i}.json")
    client = _make_app(tmp_path)
    resp = client.get("/api/runs?page=2&limit=1")
    assert resp.status_code == 200
    data = resp.json()
    assert data["page"] == 2
    assert data["limit"] == 1
    assert data["total"] == 3
    assert len(data["items"]) == 1


def test_api_runs_default_list(tmp_path: Path) -> None:
    _write_transcript(tmp_path, "transcript-20240101-120001.json")
    client = _make_app(tmp_path)
    resp = client.get("/api/runs")
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)
    assert data[0]["file"].startswith("transcript-")
