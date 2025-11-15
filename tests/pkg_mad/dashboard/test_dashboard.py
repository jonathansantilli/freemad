import json
from pathlib import Path

from fastapi.testclient import TestClient

from freemad import create_app, DashboardConfig


def _write_sample(tmp: Path) -> Path:
    tmp.mkdir(parents=True, exist_ok=True)
    p = tmp / "transcript-20250101-120000.json"
    obj = {
        "final_answer_id": "abc123",
        "final_solution": "print('ok')",
        "scores": {"abc123": 42.0, "def456": 41.0},
        "raw_scores": {"abc123": 84.0, "def456": 82.0},
        "winning_agents": ["a"],
        "validator_confidence": {"abc123": 0.8, "def456": 0.7},
        "transcript": [
            {"round": 0, "type": "generation", "agents": {
                "a": {"response": {"solution": "print('ok')", "reasoning": "initial reasoning", "decision": "KEEP", "changed": False, "answer_id": "abc123", "metadata": {}},
                       "peers_assigned": [], "peers_assigned_count": 0, "peers_seen": [], "peers_seen_count": 0}
            }, "scores": {"abc123": 20.0}, "topology_info": {"type": "all_to_all"}, "deadline_hit_soft": False, "deadline_hit_hard": False},
            {"round": 1, "type": "critique", "agents": {
                "a": {"response": {"solution": "print('ok')", "reasoning": "kept reasoning", "decision": "KEEP", "changed": False, "answer_id": "abc123", "metadata": {}},
                       "peers_assigned": [], "peers_assigned_count": 0, "peers_seen": [], "peers_seen_count": 0}
            }, "scores": {"abc123": 42.0}, "topology_info": {"type": "all_to_all"}, "deadline_hit_soft": False, "deadline_hit_hard": False},
        ],
        "metrics": {"agreement_rate": 0.5},
        "score_explainers": {"abc123": [{"round":0, "agent_id":"a", "action":"initial", "deltas": {"abc123": 20.0}, "contributors": {"abc123":1}}]},
    }
    p.write_text(json.dumps(obj), encoding="utf-8")
    return p


def test_dashboard_endpoints(tmp_path: Path):
    _write_sample(tmp_path)
    app = create_app(DashboardConfig(transcripts_dir=str(tmp_path)))
    client = TestClient(app)

    r = client.get("/health")
    assert r.status_code == 200
    r = client.get("/api/runs")
    assert r.status_code == 200
    runs = r.json()
    assert len(runs) == 1
    file = runs[0]["file"]

    r = client.get(f"/api/runs/{file}")
    assert r.status_code == 200
    data = r.json()
    assert data["final_answer_id"] == "abc123"

    r = client.get("/")
    assert r.status_code == 200
    r = client.get(f"/runs/{file}")
    assert r.status_code == 200
    html = r.text
    assert "initial reasoning" in html
    assert "Why this answer won" in html
