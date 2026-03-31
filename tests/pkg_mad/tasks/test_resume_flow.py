from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from freemad import (
    Agent,
    AgentResponse,
    CritiqueResponse,
    Decision,
    Metadata,
    ReviewDecision,
    SourceRecord,
    TaskEvent,
    TaskEventKind,
    TaskOrchestrator,
    TaskRequest,
    TaskResponse,
    TaskRole,
    TaskStage,
    TaskStatus,
    TaskType,
    load_config,
    register_agent,
)
from tests.pkg_mad.tasks.test_orchestrator import _QuorumMockAgent


class _HumanFeedbackMockAgent(Agent):
    def generate(self, requirement: str) -> AgentResponse:
        return AgentResponse(self.agent_cfg.id, "solution", "reasoning", "answer", Metadata())

    def critique_and_refine(self, requirement: str, own_response: str, peer_responses):
        return CritiqueResponse(self.agent_cfg.id, Decision.KEEP, False, own_response, "keep", "answer", Metadata())

    def act(self, request: TaskRequest) -> TaskResponse:
        if request.role == TaskRole.RESEARCHER:
            return TaskResponse(
                agent_id=self.agent_cfg.id,
                stage=request.stage,
                role=request.role,
                content="Research",
                sources=(
                    SourceRecord(
                        title="Architecture note",
                        url="https://example.com/architecture",
                        summary="Background context.",
                    ),
                ),
            )
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
                content="Plan draft",
            )
        if request.role == TaskRole.REVIEWER and request.stage == TaskStage.PLAN_REVIEW:
            feedback = " ".join(request.feedback).lower()
            if "human_input: use sqlite." in feedback and "human_approval: plan_review" in feedback:
                return TaskResponse(
                    agent_id=self.agent_cfg.id,
                    stage=request.stage,
                    role=request.role,
                    content="Plan approved after human clarification",
                    review_decision=ReviewDecision.APPROVE,
                )
            return TaskResponse(
                agent_id=self.agent_cfg.id,
                stage=request.stage,
                role=request.role,
                content="Need human clarification",
                review_decision=ReviewDecision.REJECT,
                findings=("Need explicit user confirmation",),
            )
        if request.role == TaskRole.ARBITER and request.stage == TaskStage.PLAN_REVIEW:
            return TaskResponse(
                agent_id=self.agent_cfg.id,
                stage=request.stage,
                role=request.role,
                content="Need human clarification",
                review_decision=ReviewDecision.REJECT,
                findings=("Human clarification required",),
            )
        raise AssertionError(f"Unhandled request: {request}")


def test_task_restart_and_resume_rebuilds_same_waiting_state(tmp_path: Path) -> None:
    register_agent("quorum_mock", _QuorumMockAgent)
    cfg = load_config(
        overrides={
            "agents": [
                {"id": "researcher-a", "type": "quorum_mock", "roles": ["researcher"]},
                {"id": "planner-a", "type": "quorum_mock", "roles": ["planner"]},
                {"id": "reviewer-a", "type": "quorum_mock", "roles": ["reviewer"]},
                {"id": "implementer-a", "type": "quorum_mock", "roles": ["implementer"]},
                {"id": "verifier-a", "type": "quorum_mock", "roles": ["verifier"]},
                {"id": "arbiter-a", "type": "quorum_mock", "roles": ["arbiter"]},
            ],
            "task": {
                "store_path": str(tmp_path / "tasks.db"),
                "artifacts_dir": str(tmp_path / "artifacts"),
                "max_stage_retries": 0,
                "tool_policy": {
                    "allow_workspace_write": True,
                    "allowed_write_roots": ["src"],
                    "allow_local_commands": False,
                    "verification_commands": [],
                },
            },
        }
    )
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    orch = TaskOrchestrator(cfg)
    task = orch.create_task(
        goal="Human clarification is required for this plan.",
        task_type=TaskType.PLAN,
        workspace_root=str(workspace),
    )
    first = orch.run(task.task_id)

    assert first.status == TaskStatus.WAITING_FOR_HUMAN
    assert first.current_stage == TaskStage.PLAN_REVIEW

    orch_reopened = TaskOrchestrator(cfg)
    rebuilt = orch_reopened.get_task(task.task_id)

    assert rebuilt is not None
    assert rebuilt.status == TaskStatus.WAITING_FOR_HUMAN
    assert rebuilt.current_stage == TaskStage.PLAN_REVIEW
    assert len(orch_reopened.store.list_events(task.task_id)) == len(orch.store.list_events(task.task_id))

    orch_reopened.store.update_task(replace(rebuilt, status=TaskStatus.RUNNING))
    resumed = orch_reopened.run(task.task_id)

    assert resumed.status == TaskStatus.WAITING_FOR_HUMAN
    assert resumed.current_stage == TaskStage.PLAN_REVIEW


def test_task_resume_injects_human_input_and_approval_into_feedback(tmp_path: Path) -> None:
    register_agent("human_feedback_mock", _HumanFeedbackMockAgent)
    cfg = load_config(
        overrides={
            "agents": [
                {"id": "researcher-a", "type": "human_feedback_mock", "roles": ["researcher"]},
                {"id": "planner-a", "type": "human_feedback_mock", "roles": ["planner"]},
                {"id": "reviewer-a", "type": "human_feedback_mock", "roles": ["reviewer"]},
                {"id": "arbiter-a", "type": "human_feedback_mock", "roles": ["arbiter"]},
            ],
            "task": {
                "store_path": str(tmp_path / "tasks-feedback.db"),
                "artifacts_dir": str(tmp_path / "artifacts-feedback"),
                "max_stage_retries": 0,
                "tool_policy": {
                    "allow_workspace_write": False,
                    "allow_local_commands": False,
                    "verification_commands": [],
                },
            },
        }
    )
    workspace = tmp_path / "workspace-feedback"
    workspace.mkdir()

    orch = TaskOrchestrator(cfg)
    task = orch.create_task(
        goal="Need a clarified plan.",
        task_type=TaskType.PLAN,
        workspace_root=str(workspace),
    )
    waiting = orch.run(task.task_id)

    assert waiting.status == TaskStatus.WAITING_FOR_HUMAN

    now = orch._now()
    orch.store.append_event(
        TaskEvent(
            kind=TaskEventKind.HUMAN_INPUT_RECEIVED,
            task_id=task.task_id,
            ts_ms=now,
            status=TaskStatus.WAITING_FOR_HUMAN,
            message="Use SQLite.",
        )
    )
    orch.store.append_event(
        TaskEvent(
            kind=TaskEventKind.DECISION_RECORDED,
            task_id=task.task_id,
            ts_ms=now + 1,
            status=TaskStatus.WAITING_FOR_HUMAN,
            message="plan_review",
        )
    )
    orch.store.update_task(replace(waiting, status=TaskStatus.RUNNING))

    resumed = orch.run(task.task_id)

    assert resumed.status == TaskStatus.COMPLETED
    assert resumed.current_stage == TaskStage.FINALIZE
