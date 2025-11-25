import json
from pathlib import Path

from fastapi.testclient import TestClient

from freemad import (
    Agent,
    AgentResponse,
    CritiqueResponse,
    Metadata,
    Decision,
    compute_answer_id,
    register_agent,
)
from freemad import create_app, DashboardConfig
from freemad import RunEventKind


class _APILiveAgent(Agent):
    def generate(self, requirement: str) -> AgentResponse:
        sol = f"SOLUTION_{self.agent_cfg.id}"
        return AgentResponse(
            agent_id=self.agent_cfg.id,
            solution=sol,
            reasoning="gen",
            answer_id=compute_answer_id(sol),
            metadata=Metadata(),
        )

    def critique_and_refine(self, requirement: str, own_response: str, peer_responses):
        return CritiqueResponse(
            agent_id=self.agent_cfg.id,
            decision=Decision.KEEP,
            changed=False,
            solution=own_response,
            reasoning="keep",
            answer_id=compute_answer_id(own_response),
            metadata=Metadata(),
        )


def test_live_run_websocket(tmp_path: Path):
    # Ensure agent type is registered
    register_agent("api_live", _APILiveAgent)

    app = create_app(DashboardConfig(transcripts_dir=str(tmp_path)))
    client = TestClient(app)

    overrides = {
        "agents": [
            {"id": "a1", "type": "api_live"},
            {"id": "a2", "type": "api_live"},
        ],
        "deadlines": {"soft_timeout_ms": 50, "hard_timeout_ms": 100, "min_agents": 2},
        "budget": {"max_total_time_sec": 10, "max_round_time_sec": 2, "max_agent_time_sec": 2},
    }

    r = client.post(
        "/api/live-runs",
        json={"requirement": "do something", "max_rounds": 1, "overrides": overrides},
    )
    assert r.status_code == 200
    run_id = r.json()["run_id"]
    assert run_id

    kinds = []
    with client.websocket_connect(f"/ws/live-runs/{run_id}") as ws:
        while True:
            msg = ws.receive_json()
            event = msg.get("event") or {}
            kind = event.get("kind")
            if kind:
                kinds.append(kind)
            if kind in {RunEventKind.RUN_COMPLETED.value, RunEventKind.RUN_FAILED.value, RunEventKind.RUN_BUDGET_EXCEEDED.value}:
                break

    assert RunEventKind.RUN_STARTED.value in kinds
    assert any(
        k in {RunEventKind.RUN_COMPLETED.value, RunEventKind.RUN_FAILED.value, RunEventKind.RUN_BUDGET_EXCEEDED.value}
        for k in kinds
    )

