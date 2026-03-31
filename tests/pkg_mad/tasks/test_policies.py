from __future__ import annotations

from pathlib import Path

from freemad import (
    Agent,
    AgentResponse,
    Config,
    CritiqueResponse,
    Decision,
    FileWrite,
    Metadata,
    ReviewDecision,
    TaskOrchestrator,
    TaskRequest,
    TaskResponse,
    TaskRole,
    TaskStage,
    TaskStatus,
    TaskType,
    WorkItem,
    WorkItemStatus,
    load_config,
    register_agent,
)


class _PolicyMockAgent(Agent):
    def generate(self, requirement: str) -> AgentResponse:
        return AgentResponse(self.agent_cfg.id, "solution", "reasoning", "answer", Metadata())

    def critique_and_refine(self, requirement: str, own_response: str, peer_responses):
        return CritiqueResponse(self.agent_cfg.id, Decision.KEEP, False, own_response, "keep", "answer", Metadata())

    def act(self, request: TaskRequest) -> TaskResponse:
        if request.role == TaskRole.RESEARCHER:
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
            return TaskResponse(
                agent_id=self.agent_cfg.id,
                stage=request.stage,
                role=request.role,
                content="Plan",
                work_items=(
                    WorkItem(
                        work_item_id="w-1",
                        task_id=request.task_id,
                        title="Implement",
                        description="Implement work item",
                        write_scope=("src/inside.txt",),
                        verification_scope=("src/inside.txt",),
                        status=WorkItemStatus.QUEUED,
                    ),
                ),
            )
        if request.role == TaskRole.REVIEWER and request.stage == TaskStage.PLAN_REVIEW:
            return TaskResponse(
                agent_id=self.agent_cfg.id,
                stage=request.stage,
                role=request.role,
                content="Plan approved",
                review_decision=ReviewDecision.APPROVE,
            )
        if request.role == TaskRole.IMPLEMENTER:
            if "write outside" in request.goal.lower():
                return TaskResponse(
                    agent_id=self.agent_cfg.id,
                    stage=request.stage,
                    role=request.role,
                    content="Bad write",
                    writes=(FileWrite(path="../escape.txt", content="bad\n"),),
                )
            return TaskResponse(
                agent_id=self.agent_cfg.id,
                stage=request.stage,
                role=request.role,
                content="Blocked command",
                commands=("python -c print(1)",),
            )
        if request.role == TaskRole.REVIEWER and request.stage == TaskStage.CODE_REVIEW:
            return TaskResponse(
                agent_id=self.agent_cfg.id,
                stage=request.stage,
                role=request.role,
                content="Code approved",
                review_decision=ReviewDecision.APPROVE,
            )
        if request.role == TaskRole.VERIFIER:
            return TaskResponse(
                agent_id=self.agent_cfg.id,
                stage=request.stage,
                role=request.role,
                content="Verification approved",
                review_decision=ReviewDecision.APPROVE,
            )
        raise AssertionError(f"Unhandled request: {request}")


def _build_cfg(tmp_path: Path) -> Config:
    register_agent("policy_mock", _PolicyMockAgent)
    return load_config(
        overrides={
            "agents": [
                {"id": "researcher-a", "type": "policy_mock", "roles": ["researcher"]},
                {"id": "planner-a", "type": "policy_mock", "roles": ["planner"]},
                {"id": "reviewer-a", "type": "policy_mock", "roles": ["reviewer"]},
                {"id": "implementer-a", "type": "policy_mock", "roles": ["implementer"]},
                {"id": "verifier-a", "type": "policy_mock", "roles": ["verifier"]},
            ],
            "task": {
                "store_path": str(tmp_path / "tasks.db"),
                "artifacts_dir": str(tmp_path / "artifacts"),
                "tool_policy": {
                    "allow_workspace_write": True,
                    "allowed_write_roots": ["src"],
                    "allow_local_commands": True,
                    "allowed_local_commands": ["pytest"],
                    "verification_commands": [],
                },
            },
        }
    )


def test_orchestrator_fails_when_write_root_policy_is_violated(tmp_path: Path) -> None:
    cfg = _build_cfg(tmp_path)
    workspace = tmp_path / "workspace-write"
    workspace.mkdir()
    (workspace / "src").mkdir()

    orch = TaskOrchestrator(cfg)
    task = orch.create_task(
        goal="Write outside the allowed root.",
        task_type=TaskType.CODE,
        workspace_root=str(workspace),
    )
    result = orch.run(task.task_id)

    assert result.status == TaskStatus.FAILED
    assert "outside allowed roots" in (result.error or "")


def test_orchestrator_fails_when_command_is_not_allowlisted(tmp_path: Path) -> None:
    cfg = _build_cfg(tmp_path)
    workspace = tmp_path / "workspace-command"
    workspace.mkdir()
    (workspace / "src").mkdir()

    orch = TaskOrchestrator(cfg)
    task = orch.create_task(
        goal="Command blocked by policy.",
        task_type=TaskType.CODE,
        workspace_root=str(workspace),
    )
    result = orch.run(task.task_id)

    assert result.status == TaskStatus.FAILED
    assert "not allowed" in (result.error or "")
