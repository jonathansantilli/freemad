from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Optional, Tuple

from freemad.types import (
    ActionKind,
    ArtifactKind,
    ReviewDecision,
    TaskOutcome,
    TaskRole,
    TaskStage,
    TaskStatus,
    TaskType,
    WorkItemStatus,
)


@dataclass(frozen=True)
class SourceRecord:
    title: str
    url: str
    summary: str = ""

    def to_dict(self) -> Dict[str, str]:
        return {
            "title": self.title,
            "url": self.url,
            "summary": self.summary,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> SourceRecord:
        return cls(
            title=str(data.get("title", "")).strip(),
            url=str(data.get("url", "")).strip(),
            summary=str(data.get("summary", "")),
        )


@dataclass(frozen=True)
class ArtifactRef:
    artifact_id: str
    task_id: str
    stage: TaskStage
    kind: ArtifactKind
    path: str
    created_by_agent_id: str
    created_ts_ms: int
    summary: str = ""
    parent_artifact_ids: Tuple[str, ...] = ()
    role: Optional[TaskRole] = None

    def to_dict(self) -> Dict[str, Any]:
        data: Dict[str, Any] = {
            "artifact_id": self.artifact_id,
            "task_id": self.task_id,
            "stage": self.stage.value,
            "kind": self.kind.value,
            "path": self.path,
            "created_by_agent_id": self.created_by_agent_id,
            "created_ts_ms": self.created_ts_ms,
            "summary": self.summary,
            "parent_artifact_ids": list(self.parent_artifact_ids),
        }
        if self.role is not None:
            data["role"] = self.role.value
        return data


@dataclass(frozen=True)
class FileWrite:
    path: str
    content: str

    def to_dict(self) -> Dict[str, str]:
        return {
            "path": self.path,
            "content": self.content,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> FileWrite:
        return cls(
            path=str(data.get("path", "")).strip(),
            content=str(data.get("content", "")),
        )


@dataclass(frozen=True)
class ReviewRecord:
    artifact_id: str
    reviewer_agent_id: str
    decision: ReviewDecision
    findings: Tuple[str, ...] = ()
    ts_ms: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "artifact_id": self.artifact_id,
            "reviewer_agent_id": self.reviewer_agent_id,
            "decision": self.decision.value,
            "findings": list(self.findings),
            "ts_ms": self.ts_ms,
        }


@dataclass(frozen=True)
class WorkItem:
    work_item_id: str
    task_id: str
    title: str
    description: str
    depends_on: Tuple[str, ...] = ()
    write_scope: Tuple[str, ...] = ()
    verification_scope: Tuple[str, ...] = ()
    status: WorkItemStatus = WorkItemStatus.QUEUED
    author_agent_id: Optional[str] = None
    reviewer_agent_id: Optional[str] = None
    arbiter_agent_id: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        data: Dict[str, Any] = {
            "work_item_id": self.work_item_id,
            "task_id": self.task_id,
            "title": self.title,
            "description": self.description,
            "depends_on": list(self.depends_on),
            "write_scope": list(self.write_scope),
            "verification_scope": list(self.verification_scope),
            "status": self.status.value,
        }
        if self.author_agent_id is not None:
            data["author_agent_id"] = self.author_agent_id
        if self.reviewer_agent_id is not None:
            data["reviewer_agent_id"] = self.reviewer_agent_id
        if self.arbiter_agent_id is not None:
            data["arbiter_agent_id"] = self.arbiter_agent_id
        return data

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> WorkItem:
        return cls(
            work_item_id=str(data.get("work_item_id", "")).strip(),
            task_id=str(data.get("task_id", "")).strip(),
            title=str(data.get("title", "")).strip(),
            description=str(data.get("description", "")).strip(),
            depends_on=tuple(str(item) for item in list(data.get("depends_on", []) or [])),
            write_scope=tuple(str(item) for item in list(data.get("write_scope", []) or [])),
            verification_scope=tuple(str(item) for item in list(data.get("verification_scope", []) or [])),
            status=WorkItemStatus(str(data.get("status", WorkItemStatus.QUEUED.value))),
            author_agent_id=(str(data["author_agent_id"]).strip() if data.get("author_agent_id") else None),
            reviewer_agent_id=(str(data["reviewer_agent_id"]).strip() if data.get("reviewer_agent_id") else None),
            arbiter_agent_id=(str(data["arbiter_agent_id"]).strip() if data.get("arbiter_agent_id") else None),
        )


@dataclass(frozen=True)
class StageAttempt:
    stage: TaskStage
    attempt_index: int
    proposer_agent_id: str
    reviewer_agent_id: str
    arbiter_agent_id: Optional[str] = None
    input_artifact_ids: Tuple[str, ...] = ()
    output_artifact_ids: Tuple[str, ...] = ()
    outcome: Optional[TaskOutcome] = None
    decision_reason: str = ""

    def to_dict(self) -> Dict[str, Any]:
        data: Dict[str, Any] = {
            "stage": self.stage.value,
            "attempt_index": self.attempt_index,
            "proposer_agent_id": self.proposer_agent_id,
            "reviewer_agent_id": self.reviewer_agent_id,
            "input_artifact_ids": list(self.input_artifact_ids),
            "output_artifact_ids": list(self.output_artifact_ids),
            "decision_reason": self.decision_reason,
        }
        if self.arbiter_agent_id is not None:
            data["arbiter_agent_id"] = self.arbiter_agent_id
        if self.outcome is not None:
            data["outcome"] = self.outcome.value
        return data


@dataclass(frozen=True)
class TaskSnapshot:
    task_id: str
    goal: str
    task_type: TaskType
    status: TaskStatus
    current_stage: TaskStage
    workspace_root: str
    iteration: int = 0
    stage_attempts: Tuple[StageAttempt, ...] = ()
    artifacts: Tuple[ArtifactRef, ...] = ()
    work_items: Tuple[WorkItem, ...] = ()
    error: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        data: Dict[str, Any] = {
            "task_id": self.task_id,
            "goal": self.goal,
            "task_type": self.task_type.value,
            "status": self.status.value,
            "current_stage": self.current_stage.value,
            "workspace_root": self.workspace_root,
            "iteration": self.iteration,
            "stage_attempts": [attempt.to_dict() for attempt in self.stage_attempts],
            "artifacts": [artifact.to_dict() for artifact in self.artifacts],
            "work_items": [work_item.to_dict() for work_item in self.work_items],
        }
        if self.error is not None:
            data["error"] = self.error
        return data


@dataclass(frozen=True)
class TaskRequest:
    task_id: str
    goal: str
    stage: TaskStage
    role: TaskRole
    workspace_root: str
    allowed_actions: Tuple[ActionKind, ...]
    task_type: Optional[TaskType] = None
    artifact_refs: Tuple[ArtifactRef, ...] = ()
    feedback: Tuple[str, ...] = ()
    work_item: Optional[WorkItem] = None
    required_output_kind: Optional[ArtifactKind] = None
    write_scope: Tuple[str, ...] = ()
    verification_scope: Tuple[str, ...] = ()

    def to_dict(self) -> Dict[str, Any]:
        data: Dict[str, Any] = {
            "task_id": self.task_id,
            "goal": self.goal,
            "stage": self.stage.value,
            "role": self.role.value,
            "workspace_root": self.workspace_root,
            "allowed_actions": [action.value for action in self.allowed_actions],
            "artifact_refs": [artifact.to_dict() for artifact in self.artifact_refs],
            "feedback": list(self.feedback),
            "write_scope": list(self.write_scope),
            "verification_scope": list(self.verification_scope),
        }
        if self.task_type is not None:
            data["task_type"] = self.task_type.value
        if self.work_item is not None:
            data["work_item"] = self.work_item.to_dict()
        if self.required_output_kind is not None:
            data["required_output_kind"] = self.required_output_kind.value
        return data

    def to_prompt_dict(self) -> Dict[str, Any]:
        return self.to_dict()


@dataclass(frozen=True)
class TaskResponse:
    agent_id: str
    stage: TaskStage
    role: TaskRole
    content: str
    review_decision: Optional[ReviewDecision] = None
    findings: Tuple[str, ...] = ()
    commands: Tuple[str, ...] = ()
    artifact_ids: Tuple[str, ...] = ()
    work_items: Tuple[WorkItem, ...] = ()
    writes: Tuple[FileWrite, ...] = ()
    sources: Tuple[SourceRecord, ...] = ()

    def to_dict(self) -> Dict[str, Any]:
        data: Dict[str, Any] = {
            "agent_id": self.agent_id,
            "stage": self.stage.value,
            "role": self.role.value,
            "content": self.content,
            "findings": list(self.findings),
            "commands": list(self.commands),
            "artifact_ids": list(self.artifact_ids),
            "work_items": [work_item.to_dict() for work_item in self.work_items],
            "writes": [write.to_dict() for write in self.writes],
            "sources": [source.to_dict() for source in self.sources],
        }
        if self.review_decision is not None:
            data["review_decision"] = self.review_decision.value
        return data

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> TaskResponse:
        return cls(
            agent_id=str(data.get("agent_id", "")).strip(),
            stage=TaskStage(str(data.get("stage", TaskStage.INTAKE.value))),
            role=TaskRole(str(data.get("role", TaskRole.REVIEWER.value))),
            content=str(data.get("content", "")),
            review_decision=(
                ReviewDecision(str(data["review_decision"]))
                if data.get("review_decision") is not None
                else None
            ),
            findings=tuple(str(item) for item in list(data.get("findings", []) or [])),
            commands=tuple(str(item) for item in list(data.get("commands", []) or [])),
            artifact_ids=tuple(str(item) for item in list(data.get("artifact_ids", []) or [])),
            work_items=tuple(WorkItem.from_dict(item) for item in list(data.get("work_items", []) or [])),
            writes=tuple(FileWrite.from_dict(item) for item in list(data.get("writes", []) or [])),
            sources=tuple(SourceRecord.from_dict(item) for item in list(data.get("sources", []) or [])),
        )
