from __future__ import annotations

import concurrent.futures
from dataclasses import replace
import json
from pathlib import Path
import shlex
import subprocess
import time
from typing import Iterable, List, Optional, Sequence, Tuple

from freemad.agents.factory import AgentFactory
from freemad.config import Config, ConfigError
from freemad.task_events import NullTaskObserver, TaskEvent, TaskObserver
from freemad.tasks.models import ArtifactRef, FileWrite, StageAttempt, TaskRequest, TaskResponse, TaskSnapshot, WorkItem
from freemad.tasks.store import TaskStore
from freemad.types import (
    ActionKind,
    ArtifactKind,
    ReviewDecision,
    TaskEventKind,
    TaskOutcome,
    TaskRole,
    TaskStage,
    TaskStatus,
    TaskType,
    WorkItemStatus,
)
from freemad.utils.budget import enforce_size


class TaskOrchestrator:
    def __init__(self, cfg: Config, observer: Optional[TaskObserver] = None):
        self.cfg = cfg
        self.store = TaskStore(cfg.task.store_path, cfg.task.artifacts_dir)
        self.factory = AgentFactory(cfg)
        self.agents = self.factory.build_all()
        self._observer = observer or NullTaskObserver()

    def create_task(self, goal: str, task_type: TaskType, workspace_root: str) -> TaskSnapshot:
        task = self.store.create_task(goal=goal, task_type=task_type, workspace_root=workspace_root)
        self._emit(TaskEvent(kind=TaskEventKind.TASK_CREATED, task_id=task.task_id, ts_ms=self._now(), status=task.status))
        return task

    def get_task(self, task_id: str) -> Optional[TaskSnapshot]:
        return self.store.get_task(task_id)

    def run(self, task_id: str) -> TaskSnapshot:
        task = self._require_task(task_id)
        terminal = {
            TaskStatus.COMPLETED,
            TaskStatus.PAUSED,
            TaskStatus.FAILED,
            TaskStatus.WAITING_FOR_HUMAN,
        }
        while task.status not in terminal:
            task = self.step(task.task_id)
        return task

    def step(self, task_id: str) -> TaskSnapshot:
        task = self._require_task(task_id)
        if task.status in {
            TaskStatus.COMPLETED,
            TaskStatus.PAUSED,
            TaskStatus.FAILED,
            TaskStatus.WAITING_FOR_HUMAN,
        }:
            return task
        if task.iteration >= self.cfg.task.max_total_iterations:
            return self._pause(task, "max_total_iterations_exceeded")

        task = self._mark_running(task)
        try:
            if task.current_stage == TaskStage.INTAKE:
                task = self._persist(replace(task, current_stage=TaskStage.RESEARCH))

            if task.current_stage == TaskStage.RESEARCH:
                return self._run_research(task)
            if task.current_stage == TaskStage.DRAFT_PLAN:
                return self._run_draft_plan(task)
            if task.current_stage == TaskStage.PLAN_REVIEW:
                return self._run_plan_review(task)
            if task.current_stage == TaskStage.EXECUTE:
                return self._run_execute(task)
            if task.current_stage == TaskStage.CODE_REVIEW:
                return self._run_code_review(task)
            if task.current_stage == TaskStage.VERIFY:
                return self._run_verify(task)
            if task.current_stage == TaskStage.FINALIZE:
                return self._run_finalize(task)
            return self._fail(task, f"unknown task stage: {task.current_stage.value}")
        except ConfigError as exc:
            return self._fail(self._require_task(task_id), str(exc))
        except subprocess.TimeoutExpired as exc:
            return self._fail(self._require_task(task_id), f"command timed out: {exc.cmd}")
        except Exception as exc:  # pragma: no cover - defensive boundary
            return self._fail(self._require_task(task_id), f"autonomous task crashed: {exc}")

    def _run_research(self, task: TaskSnapshot) -> TaskSnapshot:
        self._emit_stage_started(task, TaskStage.RESEARCH, TaskRole.RESEARCHER)
        proposer = self._select_agent_for_role(TaskRole.RESEARCHER)
        response = self._invoke_agent(proposer, task, TaskRole.RESEARCHER, TaskStage.RESEARCH)
        artifact = self._record_artifact(
            task,
            kind=ArtifactKind.RESEARCH_BUNDLE,
            stage=TaskStage.RESEARCH,
            role=TaskRole.RESEARCHER,
            content=response.content,
            created_by_agent_id=proposer.agent_cfg.id,
            summary=response.content[:200],
        )
        output_artifact_ids = [artifact.artifact_id]
        if response.sources:
            source_artifact = self._record_artifact(
                task,
                kind=ArtifactKind.SOURCE_BUNDLE,
                stage=TaskStage.RESEARCH,
                role=TaskRole.RESEARCHER,
                content=json.dumps([source.to_dict() for source in response.sources], indent=2, sort_keys=True),
                created_by_agent_id=proposer.agent_cfg.id,
                summary=f"{len(response.sources)} sources",
                parent_artifact_ids=(artifact.artifact_id,),
            )
            output_artifact_ids.append(source_artifact.artifact_id)
        checker = self._select_agent_for_role(TaskRole.REVIEWER, exclude={proposer.agent_cfg.id})
        if checker is None:
            checker = self._select_agent_for_role(TaskRole.RESEARCHER, exclude={proposer.agent_cfg.id})
        if checker is None:
            return self._pause(task, "missing_research_checker")
        review = self._invoke_agent(checker, task, TaskRole.REVIEWER, TaskStage.RESEARCH)
        decision = review.review_decision or ReviewDecision.APPROVE
        updated = self._append_attempt(
            task,
            StageAttempt(
                stage=TaskStage.RESEARCH,
                attempt_index=self._next_attempt_index(task, TaskStage.RESEARCH),
                proposer_agent_id=proposer.agent_cfg.id,
                reviewer_agent_id=checker.agent_cfg.id,
                output_artifact_ids=tuple(output_artifact_ids),
                outcome=self._decision_to_outcome(decision),
                decision_reason=review.content,
            ),
        )
        if decision == ReviewDecision.APPROVE:
            return self._persist(
                replace(
                    updated,
                    current_stage=TaskStage.DRAFT_PLAN,
                    iteration=updated.iteration + 1,
                )
            )
        return self._pause(updated, "research_not_approved")

    def _run_draft_plan(self, task: TaskSnapshot) -> TaskSnapshot:
        self._emit_stage_started(task, TaskStage.DRAFT_PLAN, TaskRole.PLANNER)
        proposer = self._select_agent_for_role(TaskRole.PLANNER)
        response = self._invoke_agent(proposer, task, TaskRole.PLANNER, TaskStage.DRAFT_PLAN)
        artifact = self._record_artifact(
            task,
            kind=ArtifactKind.PLAN,
            stage=TaskStage.DRAFT_PLAN,
            role=TaskRole.PLANNER,
            content=response.content,
            created_by_agent_id=proposer.agent_cfg.id,
            summary=response.content[:200],
        )
        work_items = tuple(self._normalize_work_item(item, task.task_id) for item in response.work_items)
        if work_items:
            self.store.save_work_items(task.task_id, work_items)
            for work_item in work_items:
                self._emit(
                    TaskEvent(
                        kind=TaskEventKind.WORK_ITEM_CREATED,
                        task_id=task.task_id,
                        ts_ms=self._now(),
                        stage=TaskStage.DRAFT_PLAN,
                        artifact_id=artifact.artifact_id,
                        work_item_id=work_item.work_item_id,
                    )
                )
        return self._persist(
            replace(
                task,
                current_stage=TaskStage.PLAN_REVIEW,
                iteration=task.iteration + 1,
                work_items=work_items if work_items else task.work_items,
            )
        )

    def _run_plan_review(self, task: TaskSnapshot) -> TaskSnapshot:
        self._emit_stage_started(task, TaskStage.PLAN_REVIEW, TaskRole.REVIEWER)
        proposer = self._select_agent_for_role(TaskRole.PLANNER)
        reviewer = self._select_agent_for_role(TaskRole.REVIEWER, exclude={proposer.agent_cfg.id} if proposer else set())
        if reviewer is None:
            return self._pause(task, "missing_plan_reviewer")
        response = self._invoke_agent(reviewer, task, TaskRole.REVIEWER, TaskStage.PLAN_REVIEW)
        decision = response.review_decision or ReviewDecision.REJECT
        review_artifact = self._record_artifact(
            task,
            kind=ArtifactKind.REVIEW,
            stage=TaskStage.PLAN_REVIEW,
            role=TaskRole.REVIEWER,
            content=response.content,
            created_by_agent_id=reviewer.agent_cfg.id,
            summary=response.content[:200],
        )
        updated = self._append_attempt(
            task,
            StageAttempt(
                stage=TaskStage.PLAN_REVIEW,
                attempt_index=self._next_attempt_index(task, TaskStage.PLAN_REVIEW),
                proposer_agent_id=proposer.agent_cfg.id if proposer is not None else "",
                reviewer_agent_id=reviewer.agent_cfg.id,
                output_artifact_ids=(review_artifact.artifact_id,),
                outcome=self._decision_to_outcome(decision),
                decision_reason=response.content,
            ),
        )
        self._emit_review_event(updated, TaskStage.PLAN_REVIEW, reviewer.agent_cfg.id, decision, response.findings)
        if decision == ReviewDecision.APPROVE:
            next_stage = TaskStage.FINALIZE if updated.task_type == TaskType.PLAN else TaskStage.EXECUTE
            return self._persist(replace(updated, current_stage=next_stage, iteration=updated.iteration + 1))
        return self._resolve_review_dispute(
            updated,
            stage=TaskStage.PLAN_REVIEW,
            proposer_agent_id=proposer.agent_cfg.id if proposer is not None else "",
            reviewer_agent_id=reviewer.agent_cfg.id,
            retry_stage=TaskStage.DRAFT_PLAN,
        )

    def _run_execute(self, task: TaskSnapshot) -> TaskSnapshot:
        self._emit_stage_started(task, TaskStage.EXECUTE, TaskRole.IMPLEMENTER)
        work_items = list(self.store.list_work_items(task.task_id))
        if not work_items:
            return self._pause(task, "missing_work_items")
        for group in self._partition_work_items(work_items):
            if len(group) == 1:
                self._execute_work_item(task, group[0])
                continue
            max_workers = len(group)
            if self.cfg.budget.max_concurrent_agents is not None:
                max_workers = max(1, min(max_workers, self.cfg.budget.max_concurrent_agents))
            with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
                futures = [executor.submit(self._execute_work_item, task, work_item) for work_item in group]
                for future in concurrent.futures.as_completed(futures):
                    future.result()
        return self._persist(replace(self._require_task(task.task_id), current_stage=TaskStage.CODE_REVIEW, iteration=task.iteration + 1))

    def _run_code_review(self, task: TaskSnapshot) -> TaskSnapshot:
        self._emit_stage_started(task, TaskStage.CODE_REVIEW, TaskRole.REVIEWER)
        implementer = self._select_agent_for_role(TaskRole.IMPLEMENTER)
        reviewer = self._select_agent_for_role(TaskRole.REVIEWER, exclude={implementer.agent_cfg.id} if implementer else set())
        if reviewer is None:
            return self._pause(task, "missing_code_reviewer")
        response = self._invoke_agent(reviewer, task, TaskRole.REVIEWER, TaskStage.CODE_REVIEW)
        decision = response.review_decision or ReviewDecision.REJECT
        review_artifact = self._record_artifact(
            task,
            kind=ArtifactKind.REVIEW,
            stage=TaskStage.CODE_REVIEW,
            role=TaskRole.REVIEWER,
            content=response.content,
            created_by_agent_id=reviewer.agent_cfg.id,
            summary=response.content[:200],
        )
        updated = self._append_attempt(
            task,
            StageAttempt(
                stage=TaskStage.CODE_REVIEW,
                attempt_index=self._next_attempt_index(task, TaskStage.CODE_REVIEW),
                proposer_agent_id=implementer.agent_cfg.id if implementer is not None else "",
                reviewer_agent_id=reviewer.agent_cfg.id,
                output_artifact_ids=(review_artifact.artifact_id,),
                outcome=self._decision_to_outcome(decision),
                decision_reason=response.content,
            ),
        )
        self._emit_review_event(updated, TaskStage.CODE_REVIEW, reviewer.agent_cfg.id, decision, response.findings)
        if decision == ReviewDecision.APPROVE:
            return self._persist(replace(updated, current_stage=TaskStage.VERIFY, iteration=updated.iteration + 1))
        return self._resolve_review_dispute(
            updated,
            stage=TaskStage.CODE_REVIEW,
            proposer_agent_id=implementer.agent_cfg.id if implementer is not None else "",
            reviewer_agent_id=reviewer.agent_cfg.id,
            retry_stage=TaskStage.EXECUTE,
        )

    def _run_verify(self, task: TaskSnapshot) -> TaskSnapshot:
        self._emit_stage_started(task, TaskStage.VERIFY, TaskRole.VERIFIER)
        self._emit(
            TaskEvent(
                kind=TaskEventKind.VERIFICATION_STARTED,
                task_id=task.task_id,
                ts_ms=self._now(),
                stage=TaskStage.VERIFY,
                role=TaskRole.VERIFIER,
            )
        )
        for command in self.cfg.task.tool_policy.verification_commands:
            result = self._run_command(task, command, stage=TaskStage.VERIFY)
            if result.returncode != 0:
                return self._resolve_review_dispute(
                    task,
                    stage=TaskStage.VERIFY,
                    proposer_agent_id="",
                    reviewer_agent_id="verification_commands",
                    retry_stage=TaskStage.EXECUTE,
                )
        implementer = self._select_agent_for_role(TaskRole.IMPLEMENTER)
        verifier = self._select_agent_for_role(TaskRole.VERIFIER, exclude={implementer.agent_cfg.id} if implementer else set())
        if verifier is None:
            return self._pause(task, "missing_verifier")
        response = self._invoke_agent(verifier, task, TaskRole.VERIFIER, TaskStage.VERIFY)
        decision = response.review_decision or ReviewDecision.REJECT
        verification_artifact = self._record_artifact(
            task,
            kind=ArtifactKind.VERIFICATION_REPORT,
            stage=TaskStage.VERIFY,
            role=TaskRole.VERIFIER,
            content=response.content,
            created_by_agent_id=verifier.agent_cfg.id,
            summary=response.content[:200],
        )
        updated = self._append_attempt(
            task,
            StageAttempt(
                stage=TaskStage.VERIFY,
                attempt_index=self._next_attempt_index(task, TaskStage.VERIFY),
                proposer_agent_id=implementer.agent_cfg.id if implementer is not None else "",
                reviewer_agent_id=verifier.agent_cfg.id,
                output_artifact_ids=(verification_artifact.artifact_id,),
                outcome=self._decision_to_outcome(decision),
                decision_reason=response.content,
            ),
        )
        self._emit_review_event(updated, TaskStage.VERIFY, verifier.agent_cfg.id, decision, response.findings)
        if decision == ReviewDecision.APPROVE:
            self._emit(
                TaskEvent(
                    kind=TaskEventKind.VERIFICATION_COMPLETED,
                    task_id=task.task_id,
                    ts_ms=self._now(),
                    stage=TaskStage.VERIFY,
                    role=TaskRole.VERIFIER,
                    review_decision=decision,
                )
            )
            return self._persist(replace(updated, current_stage=TaskStage.FINALIZE, iteration=updated.iteration + 1))
        return self._resolve_review_dispute(
            updated,
            stage=TaskStage.VERIFY,
            proposer_agent_id=implementer.agent_cfg.id if implementer is not None else "",
            reviewer_agent_id=verifier.agent_cfg.id,
            retry_stage=TaskStage.EXECUTE,
        )

    def _run_finalize(self, task: TaskSnapshot) -> TaskSnapshot:
        self._emit_stage_started(task, TaskStage.FINALIZE, TaskRole.PLANNER)
        artifacts = self.store.list_artifacts(task.task_id)
        content = "\n".join(
            [
                f"Goal: {task.goal}",
                f"Task type: {task.task_type.value}",
                f"Workspace: {task.workspace_root}",
                "Artifacts:",
                *[f"- {artifact.kind.value}: {artifact.path}" for artifact in artifacts],
            ]
        )
        self._record_artifact(
            task,
            kind=ArtifactKind.FINAL_SUMMARY,
            stage=TaskStage.FINALIZE,
            role=TaskRole.PLANNER,
            content=content,
            created_by_agent_id=self._select_agent_for_role(TaskRole.PLANNER).agent_cfg.id,
            summary=task.goal[:200],
        )
        completed = self._persist(
            replace(
                task,
                status=TaskStatus.COMPLETED,
                current_stage=TaskStage.FINALIZE,
                iteration=task.iteration + 1,
            )
        )
        self._emit(
            TaskEvent(
                kind=TaskEventKind.TASK_COMPLETED,
                task_id=task.task_id,
                ts_ms=self._now(),
                status=TaskStatus.COMPLETED,
            )
        )
        return completed

    def _execute_work_item(self, task: TaskSnapshot, work_item: WorkItem) -> None:
        self._emit(
            TaskEvent(
                kind=TaskEventKind.WORK_ITEM_STARTED,
                task_id=task.task_id,
                ts_ms=self._now(),
                stage=TaskStage.EXECUTE,
                role=TaskRole.IMPLEMENTER,
                work_item_id=work_item.work_item_id,
            )
        )
        running = replace(work_item, status=WorkItemStatus.IN_PROGRESS)
        self.store.update_work_item(task.task_id, running)
        implementer = self._select_agent_for_role(TaskRole.IMPLEMENTER)
        response = self._invoke_agent(implementer, task, TaskRole.IMPLEMENTER, TaskStage.EXECUTE, work_item=running)
        writes = tuple(response.writes)
        if writes:
            self._apply_writes(task, writes, running)
        for command in response.commands:
            self._run_command(task, command, stage=TaskStage.EXECUTE)
        self._record_artifact(
            task,
            kind=ArtifactKind.PATCH,
            stage=TaskStage.EXECUTE,
            role=TaskRole.IMPLEMENTER,
            content=response.content,
            created_by_agent_id=implementer.agent_cfg.id,
            summary=response.content[:200],
        )
        completed = replace(running, status=WorkItemStatus.APPROVED)
        self.store.update_work_item(task.task_id, completed)
        self._emit(
            TaskEvent(
                kind=TaskEventKind.WORK_ITEM_COMPLETED,
                task_id=task.task_id,
                ts_ms=self._now(),
                stage=TaskStage.EXECUTE,
                role=TaskRole.IMPLEMENTER,
                work_item_id=work_item.work_item_id,
            )
        )

    def _invoke_agent(
        self,
        agent,
        task: TaskSnapshot,
        role: TaskRole,
        stage: TaskStage,
        *,
        work_item: Optional[WorkItem] = None,
    ) -> TaskResponse:
        request = TaskRequest(
            task_id=task.task_id,
            goal=task.goal,
            stage=stage,
            role=role,
            workspace_root=task.workspace_root,
            allowed_actions=self._allowed_actions_for_stage(stage),
            task_type=task.task_type,
            artifact_refs=tuple(self.store.list_artifacts(task.task_id)),
            feedback=self._feedback_for_task(task.task_id),
            work_item=work_item,
        )
        response = agent.act(request)
        if not isinstance(response, TaskResponse):
            raise ConfigError(f"agent {agent.agent_cfg.id} returned unsupported autonomous response type")
        return response

    def _allowed_actions_for_stage(self, stage: TaskStage) -> Tuple[ActionKind, ...]:
        if stage == TaskStage.RESEARCH:
            return (ActionKind.RESEARCH,)
        if stage == TaskStage.DRAFT_PLAN:
            return (ActionKind.PLAN,)
        if stage in (TaskStage.PLAN_REVIEW, TaskStage.CODE_REVIEW):
            return (ActionKind.REVIEW,)
        if stage == TaskStage.EXECUTE:
            return (ActionKind.IMPLEMENT, ActionKind.WRITE_FILE, ActionKind.RUN_COMMAND)
        if stage == TaskStage.VERIFY:
            return (ActionKind.VERIFY, ActionKind.RUN_COMMAND)
        return ()

    def _select_agent_for_role(self, role: TaskRole, *, exclude: Iterable[str] = ()):
        excluded = set(exclude)
        for agent_cfg in self.cfg.agents:
            if not agent_cfg.enabled or agent_cfg.id in excluded or agent_cfg.id not in self.agents:
                continue
            if role in agent_cfg.roles:
                return self.agents[agent_cfg.id]
        return None

    def _resolve_review_dispute(
        self,
        task: TaskSnapshot,
        *,
        stage: TaskStage,
        proposer_agent_id: str,
        reviewer_agent_id: str,
        retry_stage: TaskStage,
    ) -> TaskSnapshot:
        attempts = self._attempt_count(task, stage)
        if attempts <= self.cfg.task.max_stage_retries:
            return self._persist(replace(task, current_stage=retry_stage, iteration=task.iteration + 1))

        arbiter = self._select_agent_for_role(TaskRole.ARBITER, exclude=(proposer_agent_id, reviewer_agent_id))
        if arbiter is None:
            return self._pause(task, f"{stage.value}_retries_exhausted")

        self._emit(
            TaskEvent(
                kind=TaskEventKind.ARBITER_REQUESTED,
                task_id=task.task_id,
                ts_ms=self._now(),
                stage=stage,
                role=TaskRole.ARBITER,
            )
        )
        response = self._invoke_agent(arbiter, task, TaskRole.ARBITER, stage)
        decision = response.review_decision or ReviewDecision.REJECT
        updated = self._append_attempt(
            task,
            StageAttempt(
                stage=stage,
                attempt_index=self._next_attempt_index(task, stage),
                proposer_agent_id=proposer_agent_id,
                reviewer_agent_id=reviewer_agent_id,
                arbiter_agent_id=arbiter.agent_cfg.id,
                outcome=self._decision_to_outcome(decision),
                decision_reason=response.content,
            ),
        )
        if decision == ReviewDecision.APPROVE:
            next_stage = (
                TaskStage.FINALIZE
                if stage == TaskStage.PLAN_REVIEW and updated.task_type == TaskType.PLAN
                else TaskStage.EXECUTE
                if stage == TaskStage.PLAN_REVIEW
                else TaskStage.VERIFY
                if stage == TaskStage.CODE_REVIEW
                else TaskStage.FINALIZE
            )
            return self._persist(replace(updated, current_stage=next_stage, iteration=updated.iteration + 1))
        return self._wait_for_human(updated, response.findings[0] if response.findings else response.content)

    def _append_attempt(self, task: TaskSnapshot, attempt: StageAttempt) -> TaskSnapshot:
        return replace(task, stage_attempts=task.stage_attempts + (attempt,))

    def _attempt_count(self, task: TaskSnapshot, stage: TaskStage) -> int:
        return len([attempt for attempt in task.stage_attempts if attempt.stage == stage])

    def _next_attempt_index(self, task: TaskSnapshot, stage: TaskStage) -> int:
        return self._attempt_count(task, stage) + 1

    def _decision_to_outcome(self, decision: ReviewDecision) -> TaskOutcome:
        if decision == ReviewDecision.APPROVE:
            return TaskOutcome.APPROVED
        if decision == ReviewDecision.REVISE:
            return TaskOutcome.NEEDS_REVISION
        return TaskOutcome.REJECTED

    def _record_artifact(
        self,
        task: TaskSnapshot,
        *,
        kind: ArtifactKind,
        stage: TaskStage,
        role: TaskRole,
        content: str,
        created_by_agent_id: str,
        summary: str,
        parent_artifact_ids: Sequence[str] = (),
    ) -> ArtifactRef:
        artifact = self.store.save_artifact(
            task.task_id,
            kind=kind,
            stage=stage,
            content=content,
            created_by_agent_id=created_by_agent_id,
            summary=summary,
            parent_artifact_ids=parent_artifact_ids,
            role=role,
        )
        self._emit(
            TaskEvent(
                kind=TaskEventKind.ARTIFACT_CREATED,
                task_id=task.task_id,
                ts_ms=self._now(),
                stage=stage,
                role=role,
                artifact_id=artifact.artifact_id,
                artifact_kind=artifact.kind,
            )
        )
        return artifact

    def _emit_review_event(
        self,
        task: TaskSnapshot,
        stage: TaskStage,
        reviewer_agent_id: str,
        decision: ReviewDecision,
        findings: Sequence[str],
    ) -> None:
        self._emit(
            TaskEvent(
                kind=TaskEventKind.REVIEW_RECORDED,
                task_id=task.task_id,
                ts_ms=self._now(),
                stage=stage,
                role=TaskRole.REVIEWER,
                review_decision=decision,
                message="\n".join(findings) if findings else reviewer_agent_id,
            )
        )

    def _feedback_for_task(self, task_id: str) -> Tuple[str, ...]:
        feedback: List[str] = []
        for event in self.store.list_events(task_id):
            if event.message is None or not event.message.strip():
                continue
            if event.kind == TaskEventKind.HUMAN_INPUT_RECEIVED:
                feedback.append(f"HUMAN_INPUT: {event.message}")
            elif event.kind == TaskEventKind.DECISION_RECORDED:
                feedback.append(f"HUMAN_APPROVAL: {event.message}")
        return tuple(feedback)

    def _apply_writes(self, task: TaskSnapshot, writes: Sequence[FileWrite], work_item: WorkItem) -> None:
        if not self.cfg.task.tool_policy.allow_workspace_write:
            raise ConfigError("task tool policy forbids workspace writes")
        workspace_root = Path(task.workspace_root).resolve()
        for write in writes:
            relative_path = Path(write.path)
            if relative_path.is_absolute():
                raise ConfigError("autonomous writes must use relative paths")
            target = (workspace_root / relative_path).resolve()
            if not self._is_under_roots(target, workspace_root, self.cfg.task.tool_policy.allowed_write_roots):
                raise ConfigError(f"write path outside allowed roots: {write.path}")
            if work_item.write_scope and not self._is_under_roots(target, workspace_root, work_item.write_scope):
                raise ConfigError(f"write path outside work item scope: {write.path}")
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(write.content, encoding="utf-8")

    def _run_command(self, task: TaskSnapshot, command: str, *, stage: TaskStage) -> subprocess.CompletedProcess[str]:
        if not self.cfg.task.tool_policy.allow_local_commands:
            raise ConfigError("task tool policy forbids local commands")
        cmd = shlex.split(command)
        if not cmd:
            raise ConfigError("empty autonomous command")
        if cmd[0] not in self.cfg.task.tool_policy.allowed_local_commands:
            raise ConfigError(f"command '{cmd[0]}' not allowed for autonomous tasks")
        completed = subprocess.run(
            cmd,
            cwd=task.workspace_root,
            text=True,
            capture_output=True,
            timeout=self.cfg.security.cli_timeout_ms / 1000.0,
            check=False,
        )
        content = "\n".join(
            [
                f"Command: {command}",
                f"Return code: {completed.returncode}",
                "STDOUT:",
                completed.stdout or "",
                "STDERR:",
                completed.stderr or "",
            ]
        )
        content, _ = enforce_size(content, self.cfg.security.max_solution_size, label="command_log")
        role = TaskRole.VERIFIER if stage == TaskStage.VERIFY else TaskRole.IMPLEMENTER
        summary, _ = enforce_size(command, 200, label="command_summary")
        self._record_artifact(
            task,
            kind=ArtifactKind.VERIFICATION_REPORT if stage == TaskStage.VERIFY else ArtifactKind.PATCH,
            stage=stage,
            role=role,
            content=content,
            created_by_agent_id=role.value,
            summary=summary,
        )
        return completed

    def _partition_work_items(self, work_items: Sequence[WorkItem]) -> List[List[WorkItem]]:
        groups: List[List[WorkItem]] = []
        for work_item in work_items:
            scope = set(work_item.write_scope)
            placed = False
            for group in groups:
                existing_scope = {path for existing in group for path in existing.write_scope}
                if scope.isdisjoint(existing_scope):
                    group.append(work_item)
                    placed = True
                    break
            if not placed:
                groups.append([work_item])
        return groups

    def _normalize_work_item(self, work_item: WorkItem, task_id: str) -> WorkItem:
        if work_item.task_id == task_id:
            return work_item
        return replace(work_item, task_id=task_id)

    def _mark_running(self, task: TaskSnapshot) -> TaskSnapshot:
        if task.status == TaskStatus.PENDING:
            updated = self._persist(replace(task, status=TaskStatus.RUNNING))
            self._emit(
                TaskEvent(
                    kind=TaskEventKind.TASK_STARTED,
                    task_id=task.task_id,
                    ts_ms=self._now(),
                    status=TaskStatus.RUNNING,
                )
            )
            return updated
        if task.status != TaskStatus.RUNNING:
            return self._persist(replace(task, status=TaskStatus.RUNNING))
        return task

    def _emit_stage_started(self, task: TaskSnapshot, stage: TaskStage, role: TaskRole) -> None:
        self._emit(
            TaskEvent(
                kind=TaskEventKind.STAGE_STARTED,
                task_id=task.task_id,
                ts_ms=self._now(),
                stage=stage,
                role=role,
            )
        )

    def _wait_for_human(self, task: TaskSnapshot, reason: str) -> TaskSnapshot:
        waiting = self._persist(replace(task, status=TaskStatus.WAITING_FOR_HUMAN, error=reason))
        self._emit(
            TaskEvent(
                kind=TaskEventKind.HUMAN_INPUT_REQUESTED,
                task_id=task.task_id,
                ts_ms=self._now(),
                status=TaskStatus.WAITING_FOR_HUMAN,
                error=reason,
            )
        )
        return waiting

    def _pause(self, task: TaskSnapshot, reason: str) -> TaskSnapshot:
        paused = self._persist(replace(task, status=TaskStatus.PAUSED, error=reason))
        self._emit(
            TaskEvent(
                kind=TaskEventKind.TASK_PAUSED,
                task_id=task.task_id,
                ts_ms=self._now(),
                status=TaskStatus.PAUSED,
                error=reason,
            )
        )
        return paused

    def _fail(self, task: TaskSnapshot, error: str) -> TaskSnapshot:
        failed = self._persist(replace(task, status=TaskStatus.FAILED, error=error))
        self._emit(
            TaskEvent(
                kind=TaskEventKind.TASK_FAILED,
                task_id=task.task_id,
                ts_ms=self._now(),
                status=TaskStatus.FAILED,
                error=error,
            )
        )
        return failed

    def _persist(self, task: TaskSnapshot) -> TaskSnapshot:
        self.store.update_task(task)
        return task

    def _require_task(self, task_id: str) -> TaskSnapshot:
        task = self.store.get_task(task_id)
        if task is None:
            raise ConfigError(f"unknown task id: {task_id}")
        return task

    def _emit(self, event: TaskEvent) -> None:
        self.store.append_event(event)
        self._observer.on_event(event)

    def _now(self) -> int:
        return int(time.time() * 1000)

    def _is_under_roots(self, target: Path, workspace_root: Path, roots: Iterable[str]) -> bool:
        for root in roots:
            candidate = (workspace_root / root).resolve()
            if candidate == target or candidate in target.parents:
                return True
        return False
