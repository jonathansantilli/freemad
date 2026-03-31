from __future__ import annotations

from pathlib import Path
import time

from fastapi.testclient import TestClient

from freemad import (
    Agent,
    AgentResponse,
    CritiqueResponse,
    DashboardConfig,
    Decision,
    Metadata,
    ReviewDecision,
    TaskEventKind,
    TaskRequest,
    TaskResponse,
    TaskRole,
    TaskStage,
    create_app,
    register_agent,
)
from tests.pkg_mad.tasks.test_orchestrator import _QuorumMockAgent


class _SlowTaskMockAgent(Agent):
    def generate(self, requirement: str) -> AgentResponse:
        return AgentResponse(self.agent_cfg.id, "solution", "reasoning", "answer", Metadata())

    def critique_and_refine(self, requirement: str, own_response: str, peer_responses):
        return CritiqueResponse(self.agent_cfg.id, Decision.KEEP, False, own_response, "keep", "answer", Metadata())

    def act(self, request: TaskRequest) -> TaskResponse:
        if request.role == TaskRole.RESEARCHER:
            time.sleep(0.4)
            return TaskResponse(agent_id=self.agent_cfg.id, stage=request.stage, role=request.role, content="Research")
        if request.role == TaskRole.REVIEWER and request.stage == TaskStage.RESEARCH:
            return TaskResponse(
                agent_id=self.agent_cfg.id,
                stage=request.stage,
                role=request.role,
                content="Research approved",
                review_decision=ReviewDecision.APPROVE,
            )
        if request.role == TaskRole.PLANNER:
            return TaskResponse(agent_id=self.agent_cfg.id, stage=request.stage, role=request.role, content="Plan")
        if request.role == TaskRole.REVIEWER and request.stage == TaskStage.PLAN_REVIEW:
            return TaskResponse(
                agent_id=self.agent_cfg.id,
                stage=request.stage,
                role=request.role,
                content="Plan approved",
                review_decision=ReviewDecision.APPROVE,
            )
        raise AssertionError(f"Unhandled request: {request}")


def test_task_api_and_websocket(tmp_path: Path) -> None:
    register_agent("quorum_mock", _QuorumMockAgent)
    app = create_app(
        DashboardConfig(
            transcripts_dir=str(tmp_path / "transcripts"),
            task_store_path=tmp_path / "tasks.db",
            task_artifacts_dir=tmp_path / "artifacts",
        )
    )
    client = TestClient(app)

    workspace = tmp_path / "workspace"
    workspace.mkdir()

    overrides = {
        "agents": [
            {"id": "researcher-a", "type": "quorum_mock", "roles": ["researcher"]},
            {"id": "planner-a", "type": "quorum_mock", "roles": ["planner"]},
            {"id": "reviewer-a", "type": "quorum_mock", "roles": ["reviewer"]},
            {"id": "implementer-a", "type": "quorum_mock", "roles": ["implementer"]},
            {"id": "verifier-a", "type": "quorum_mock", "roles": ["verifier"]},
            {"id": "arbiter-a", "type": "quorum_mock", "roles": ["arbiter"]},
        ],
    }

    response = client.post(
        "/api/tasks",
        json={
            "goal": "Solidify the implementation plan.",
            "task_type": "plan",
            "workspace_root": str(workspace),
            "overrides": overrides,
        },
    )
    assert response.status_code == 200
    task_id = response.json()["task_id"]

    kinds: list[str] = []
    with client.websocket_connect(f"/ws/tasks/{task_id}") as ws:
        while True:
            msg = ws.receive_json()
            event = msg.get("event") or {}
            kind = event.get("kind")
            if kind:
                kinds.append(kind)
            if kind in {
                TaskEventKind.TASK_COMPLETED.value,
                TaskEventKind.TASK_FAILED.value,
                TaskEventKind.TASK_PAUSED.value,
            }:
                break

    assert TaskEventKind.TASK_CREATED.value in kinds
    assert TaskEventKind.STAGE_STARTED.value in kinds
    assert TaskEventKind.TASK_COMPLETED.value in kinds

    listing = client.get("/api/tasks")
    assert listing.status_code == 200
    assert any(task["task_id"] == task_id for task in listing.json())

    detail = client.get(f"/api/tasks/{task_id}")
    assert detail.status_code == 200
    payload = detail.json()
    assert payload["task_id"] == task_id
    assert payload["status"] == "completed"
    assert payload["snapshot"]["status"] == "completed"

    html = client.get(f"/tasks/{task_id}")
    assert html.status_code == 200
    assert "Solidify the implementation plan." in html.text

    index = client.get("/tasks")
    assert index.status_code == 200
    assert task_id in index.text


def test_task_api_runs_in_background_and_websocket_streams_live_events(tmp_path: Path) -> None:
    register_agent("slow_task_mock", _SlowTaskMockAgent)
    app = create_app(
        DashboardConfig(
            transcripts_dir=str(tmp_path / "transcripts"),
            task_store_path=tmp_path / "tasks.db",
            task_artifacts_dir=tmp_path / "artifacts",
        )
    )
    client = TestClient(app)

    workspace = tmp_path / "workspace-live"
    workspace.mkdir()

    response = client.post(
        "/api/tasks",
        json={
            "goal": "Run this task in the background.",
            "task_type": "plan",
            "workspace_root": str(workspace),
            "overrides": {
                "agents": [
                    {"id": "researcher-a", "type": "slow_task_mock", "roles": ["researcher"]},
                    {"id": "planner-a", "type": "slow_task_mock", "roles": ["planner"]},
                    {"id": "reviewer-a", "type": "slow_task_mock", "roles": ["reviewer"]},
                ],
            },
        },
    )
    assert response.status_code == 200
    task_id = response.json()["task_id"]

    detail = client.get(f"/api/tasks/{task_id}")
    assert detail.status_code == 200
    assert detail.json()["status"] in {"pending", "running"}

    kinds: list[str] = []
    with client.websocket_connect(f"/ws/tasks/{task_id}") as ws:
        while True:
            msg = ws.receive_json()
            event = msg.get("event") or {}
            kind = event.get("kind")
            if kind:
                kinds.append(kind)
            if kind in {
                TaskEventKind.TASK_COMPLETED.value,
                TaskEventKind.TASK_FAILED.value,
                TaskEventKind.TASK_PAUSED.value,
            }:
                break

    assert TaskEventKind.TASK_CREATED.value in kinds
    assert TaskEventKind.TASK_COMPLETED.value in kinds
