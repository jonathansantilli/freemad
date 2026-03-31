from __future__ import annotations

import json
from pathlib import Path
import threading

from freemad import (
    Agent,
    AgentResponse,
    CritiqueResponse,
    Decision,
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
    SourceRecord,
)
from freemad.tasks.models import FileWrite


class _QuorumMockAgent(Agent):
    def generate(self, requirement: str) -> AgentResponse:
        return AgentResponse(
            agent_id=self.agent_cfg.id,
            solution="solution",
            reasoning="reasoning",
            answer_id="answer",
            metadata=Metadata(),
        )

    def critique_and_refine(self, requirement: str, own_response: str, peer_responses):
        return CritiqueResponse(
            agent_id=self.agent_cfg.id,
            decision=Decision.KEEP,
            changed=False,
            solution=own_response,
            reasoning="keep",
            answer_id="answer",
            metadata=Metadata(),
        )

    def act(self, request: TaskRequest) -> TaskResponse:
        goal = request.goal.lower()

        if request.role == TaskRole.RESEARCHER:
            return TaskResponse(
                agent_id=self.agent_cfg.id,
                stage=request.stage,
                role=request.role,
                content="Research bundle",
                sources=(
                    SourceRecord(
                        title="FREE-MAD paper",
                        url="https://arxiv.org/html/2509.11035v1",
                        summary="Consensus-free debate with trajectory scoring.",
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

        if request.role == TaskRole.PLANNER and request.stage == TaskStage.DRAFT_PLAN:
            if request.task_type == TaskType.CODE:
                return TaskResponse(
                    agent_id=self.agent_cfg.id,
                    stage=request.stage,
                    role=request.role,
                    content="Implementation plan",
                    work_items=(
                        WorkItem(
                            work_item_id="w-1",
                            task_id=request.task_id,
                            title="Write alpha file",
                            description="Create src/alpha.txt",
                            write_scope=("src/alpha.txt",),
                            verification_scope=("src/alpha.txt",),
                            status=WorkItemStatus.QUEUED,
                            author_agent_id="implementer-a",
                            reviewer_agent_id="reviewer-a",
                        ),
                        WorkItem(
                            work_item_id="w-2",
                            task_id=request.task_id,
                            title="Write beta file",
                            description="Create src/beta.txt",
                            write_scope=("src/beta.txt",),
                            verification_scope=("src/beta.txt",),
                            status=WorkItemStatus.QUEUED,
                            author_agent_id="implementer-a",
                            reviewer_agent_id="reviewer-a",
                        ),
                    ),
                )
            return TaskResponse(
                agent_id=self.agent_cfg.id,
                stage=request.stage,
                role=request.role,
                content="Plan draft",
            )

        if request.role == TaskRole.REVIEWER and request.stage == TaskStage.PLAN_REVIEW:
            if "human" in goal or "pause" in goal or "arbiter" in goal:
                return TaskResponse(
                    agent_id=self.agent_cfg.id,
                    stage=request.stage,
                    role=request.role,
                    content="Plan rejected",
                    review_decision=ReviewDecision.REJECT,
                    findings=("Plan needs escalation",),
                )
            return TaskResponse(
                agent_id=self.agent_cfg.id,
                stage=request.stage,
                role=request.role,
                content="Plan approved",
                review_decision=ReviewDecision.APPROVE,
            )

        if request.role == TaskRole.ARBITER and request.stage == TaskStage.PLAN_REVIEW:
            if "human" in goal:
                return TaskResponse(
                    agent_id=self.agent_cfg.id,
                    stage=request.stage,
                    role=request.role,
                    content="Need human clarification",
                    review_decision=ReviewDecision.REJECT,
                    findings=("Human clarification required",),
                )
            return TaskResponse(
                agent_id=self.agent_cfg.id,
                stage=request.stage,
                role=request.role,
                content="Arbiter approved",
                review_decision=ReviewDecision.APPROVE,
            )

        if request.role == TaskRole.IMPLEMENTER and request.work_item is not None:
            if request.work_item.work_item_id == "w-1":
                writes = (FileWrite(path="src/alpha.txt", content="alpha\n"),)
            else:
                writes = (FileWrite(path="src/beta.txt", content="beta\n"),)
            return TaskResponse(
                agent_id=self.agent_cfg.id,
                stage=request.stage,
                role=request.role,
                content=f"Implemented {request.work_item.work_item_id}",
                writes=writes,
            )

        if request.role == TaskRole.REVIEWER and request.stage == TaskStage.CODE_REVIEW:
            return TaskResponse(
                agent_id=self.agent_cfg.id,
                stage=request.stage,
                role=request.role,
                content="Code review approved",
                review_decision=ReviewDecision.APPROVE,
            )

        if request.role == TaskRole.VERIFIER and request.stage == TaskStage.VERIFY:
            return TaskResponse(
                agent_id=self.agent_cfg.id,
                stage=request.stage,
                role=request.role,
                content="Verification approved",
                review_decision=ReviewDecision.APPROVE,
            )

        raise AssertionError(f"Unhandled request: {request}")


class _ParallelExecutionMockAgent(Agent):
    barrier = threading.Barrier(2)

    def generate(self, requirement: str) -> AgentResponse:
        return AgentResponse(
            agent_id=self.agent_cfg.id,
            solution="solution",
            reasoning="reasoning",
            answer_id="answer",
            metadata=Metadata(),
        )

    def critique_and_refine(self, requirement: str, own_response: str, peer_responses):
        return CritiqueResponse(
            agent_id=self.agent_cfg.id,
            decision=Decision.KEEP,
            changed=False,
            solution=own_response,
            reasoning="keep",
            answer_id="answer",
            metadata=Metadata(),
        )

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
                content="Parallel implementation plan",
                work_items=(
                    WorkItem(
                        work_item_id="w-1",
                        task_id=request.task_id,
                        title="Write one",
                        description="Create src/one.txt",
                        write_scope=("src/one.txt",),
                        verification_scope=("src/one.txt",),
                        status=WorkItemStatus.QUEUED,
                    ),
                    WorkItem(
                        work_item_id="w-2",
                        task_id=request.task_id,
                        title="Write two",
                        description="Create src/two.txt",
                        write_scope=("src/two.txt",),
                        verification_scope=("src/two.txt",),
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
        if request.role == TaskRole.IMPLEMENTER and request.work_item is not None:
            _ParallelExecutionMockAgent.barrier.wait(timeout=0.5)
            filename = "one.txt" if request.work_item.work_item_id == "w-1" else "two.txt"
            return TaskResponse(
                agent_id=self.agent_cfg.id,
                stage=request.stage,
                role=request.role,
                content=f"Implemented {request.work_item.work_item_id}",
                writes=(FileWrite(path=f"src/{filename}", content=f"{filename}\n"),),
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


def _build_cfg(tmp_path: Path, *, include_arbiter: bool = True, max_stage_retries: int = 1):
    register_agent("quorum_mock", _QuorumMockAgent)
    agents = [
        {"id": "researcher-a", "type": "quorum_mock", "roles": ["researcher"]},
        {"id": "planner-a", "type": "quorum_mock", "roles": ["planner"]},
        {"id": "reviewer-a", "type": "quorum_mock", "roles": ["reviewer"]},
        {"id": "implementer-a", "type": "quorum_mock", "roles": ["implementer"]},
        {"id": "verifier-a", "type": "quorum_mock", "roles": ["verifier"]},
    ]
    if include_arbiter:
        agents.append({"id": "arbiter-a", "type": "quorum_mock", "roles": ["arbiter"]})
    return load_config(
        overrides={
            "agents": agents,
            "task": {
                "store_path": str(tmp_path / "tasks.db"),
                "artifacts_dir": str(tmp_path / "artifacts"),
                "max_stage_retries": max_stage_retries,
                "tool_policy": {
                    "allow_workspace_write": True,
                    "allowed_write_roots": ["src"],
                    "allow_local_commands": False,
                    "verification_commands": [],
                },
            },
        }
    )


def test_plan_task_completes_after_independent_review(tmp_path: Path) -> None:
    cfg = _build_cfg(tmp_path)
    workspace = tmp_path / "workspace-plan"
    workspace.mkdir()

    orch = TaskOrchestrator(cfg)
    task = orch.create_task(goal="Solidify the implementation plan.", task_type=TaskType.PLAN, workspace_root=str(workspace))
    result = orch.run(task.task_id)

    assert result.status == TaskStatus.COMPLETED
    assert result.current_stage == TaskStage.FINALIZE


def test_research_stage_persists_source_bundle_artifact(tmp_path: Path) -> None:
    cfg = _build_cfg(tmp_path)
    workspace = tmp_path / "workspace-sources"
    workspace.mkdir()

    orch = TaskOrchestrator(cfg)
    task = orch.create_task(goal="Research the implementation plan.", task_type=TaskType.PLAN, workspace_root=str(workspace))
    result = orch.run(task.task_id)
    artifacts = orch.store.list_artifacts(task.task_id)
    source_artifacts = [artifact for artifact in artifacts if artifact.kind.value == "source_bundle"]

    assert result.status == TaskStatus.COMPLETED
    assert len(source_artifacts) == 1
    source_payload = json.loads(Path(source_artifacts[0].path).read_text(encoding="utf-8"))
    assert source_payload[0]["title"] == "FREE-MAD paper"
    assert source_payload[0]["url"] == "https://arxiv.org/html/2509.11035v1"


def test_plan_review_disagreement_uses_arbiter_after_retry(tmp_path: Path) -> None:
    cfg = _build_cfg(tmp_path, include_arbiter=True, max_stage_retries=0)
    workspace = tmp_path / "workspace-arbiter"
    workspace.mkdir()

    orch = TaskOrchestrator(cfg)
    task = orch.create_task(goal="Arbiter should break the plan-review tie.", task_type=TaskType.PLAN, workspace_root=str(workspace))
    result = orch.run(task.task_id)
    events = orch.store.list_events(task.task_id)

    assert result.status == TaskStatus.COMPLETED
    assert any(event.kind.value == "arbiter_requested" for event in events)


def test_unresolved_dispute_moves_task_to_waiting_for_human(tmp_path: Path) -> None:
    cfg = _build_cfg(tmp_path, include_arbiter=True, max_stage_retries=0)
    workspace = tmp_path / "workspace-human"
    workspace.mkdir()

    orch = TaskOrchestrator(cfg)
    task = orch.create_task(goal="Human clarification is required for this plan.", task_type=TaskType.PLAN, workspace_root=str(workspace))
    result = orch.run(task.task_id)
    events = orch.store.list_events(task.task_id)

    assert result.status == TaskStatus.WAITING_FOR_HUMAN
    assert any(event.kind.value == "human_input_requested" for event in events)


def test_retry_exhaustion_without_arbiter_pauses_task(tmp_path: Path) -> None:
    cfg = _build_cfg(tmp_path, include_arbiter=False, max_stage_retries=0)
    workspace = tmp_path / "workspace-pause"
    workspace.mkdir()

    orch = TaskOrchestrator(cfg)
    task = orch.create_task(goal="Pause when review retries are exhausted.", task_type=TaskType.PLAN, workspace_root=str(workspace))
    result = orch.run(task.task_id)

    assert result.status == TaskStatus.PAUSED


def test_code_task_writes_files_and_completes(tmp_path: Path) -> None:
    cfg = _build_cfg(tmp_path)
    workspace = tmp_path / "workspace-code"
    workspace.mkdir()
    (workspace / "src").mkdir()

    orch = TaskOrchestrator(cfg)
    task = orch.create_task(goal="Implement the approved code plan.", task_type=TaskType.CODE, workspace_root=str(workspace))
    result = orch.run(task.task_id)

    assert result.status == TaskStatus.COMPLETED
    assert (workspace / "src" / "alpha.txt").read_text(encoding="utf-8") == "alpha\n"
    assert (workspace / "src" / "beta.txt").read_text(encoding="utf-8") == "beta\n"


def test_execute_runs_non_overlapping_work_items_in_parallel(tmp_path: Path) -> None:
    register_agent("parallel_mock", _ParallelExecutionMockAgent)
    _ParallelExecutionMockAgent.barrier = threading.Barrier(2)
    cfg = load_config(
        overrides={
            "agents": [
                {"id": "researcher-a", "type": "parallel_mock", "roles": ["researcher"]},
                {"id": "planner-a", "type": "parallel_mock", "roles": ["planner"]},
                {"id": "reviewer-a", "type": "parallel_mock", "roles": ["reviewer"]},
                {"id": "implementer-a", "type": "parallel_mock", "roles": ["implementer"]},
                {"id": "verifier-a", "type": "parallel_mock", "roles": ["verifier"]},
            ],
            "task": {
                "store_path": str(tmp_path / "parallel.db"),
                "artifacts_dir": str(tmp_path / "parallel-artifacts"),
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
    workspace = tmp_path / "workspace-parallel"
    workspace.mkdir()
    (workspace / "src").mkdir()

    orch = TaskOrchestrator(cfg)
    task = orch.create_task(goal="Execute disjoint work items in parallel.", task_type=TaskType.CODE, workspace_root=str(workspace))
    result = orch.run(task.task_id)

    assert result.status == TaskStatus.COMPLETED
    assert (workspace / "src" / "one.txt").read_text(encoding="utf-8") == "one.txt\n"
    assert (workspace / "src" / "two.txt").read_text(encoding="utf-8") == "two.txt\n"


def test_partition_work_items_groups_only_non_overlapping_scopes(tmp_path: Path) -> None:
    cfg = _build_cfg(tmp_path)
    orch = TaskOrchestrator(cfg)
    work_items = [
        WorkItem(
            work_item_id="w-1",
            task_id="task-1",
            title="alpha",
            description="alpha",
            write_scope=("src/alpha.txt",),
        ),
        WorkItem(
            work_item_id="w-2",
            task_id="task-1",
            title="beta",
            description="beta",
            write_scope=("src/beta.txt",),
        ),
        WorkItem(
            work_item_id="w-3",
            task_id="task-1",
            title="alpha overlap",
            description="alpha overlap",
            write_scope=("src/alpha.txt",),
        ),
    ]

    groups = orch._partition_work_items(work_items)

    assert len(groups) == 2
    assert len(groups[0]) == 2
    assert len(groups[1]) == 1
