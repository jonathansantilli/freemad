import unittest
from dataclasses import FrozenInstanceError


class TestTaskModels(unittest.TestCase):
    def test_artifact_ref_to_dict_serializes_enums(self):
        from freemad.tasks.models import ArtifactRef
        from freemad.types import ArtifactKind, TaskRole, TaskStage

        artifact = ArtifactRef(
            artifact_id="art-1",
            task_id="task-1",
            stage=TaskStage.DRAFT_PLAN,
            kind=ArtifactKind.PLAN,
            path="artifacts/task-1/plan.md",
            created_by_agent_id="planner-a",
            created_ts_ms=123,
            summary="initial draft",
            parent_artifact_ids=("brief-1",),
            role=TaskRole.PLANNER,
        )

        self.assertEqual(
            artifact.to_dict(),
            {
                "artifact_id": "art-1",
                "task_id": "task-1",
                "stage": "draft_plan",
                "kind": "plan",
                "path": "artifacts/task-1/plan.md",
                "created_by_agent_id": "planner-a",
                "created_ts_ms": 123,
                "summary": "initial draft",
                "parent_artifact_ids": ["brief-1"],
                "role": "planner",
            },
        )

    def test_work_item_is_frozen_and_serializes_scopes(self):
        from freemad.tasks.models import WorkItem
        from freemad.types import WorkItemStatus

        work_item = WorkItem(
            work_item_id="w-1",
            task_id="task-1",
            title="Add task config",
            description="Extend config with task settings.",
            depends_on=("w-0",),
            write_scope=("freemad/config.py", "tests/pkg_mad/config/test_config.py"),
            verification_scope=("tests/pkg_mad/config/test_config.py",),
            status=WorkItemStatus.IN_REVIEW,
            author_agent_id="implementer-a",
            reviewer_agent_id="reviewer-b",
        )

        with self.assertRaises(FrozenInstanceError):
            setattr(work_item, "title", "mutated")

        self.assertEqual(
            work_item.to_dict(),
            {
                "work_item_id": "w-1",
                "task_id": "task-1",
                "title": "Add task config",
                "description": "Extend config with task settings.",
                "depends_on": ["w-0"],
                "write_scope": ["freemad/config.py", "tests/pkg_mad/config/test_config.py"],
                "verification_scope": ["tests/pkg_mad/config/test_config.py"],
                "status": "in_review",
                "author_agent_id": "implementer-a",
                "reviewer_agent_id": "reviewer-b",
            },
        )

    def test_stage_attempt_and_review_record_use_typed_decisions(self):
        from freemad.tasks.models import ReviewRecord, StageAttempt
        from freemad.types import ReviewDecision, TaskOutcome, TaskStage

        review = ReviewRecord(
            artifact_id="art-2",
            reviewer_agent_id="reviewer-b",
            decision=ReviewDecision.REVISE,
            findings=("missing rollback", "missing tests"),
            ts_ms=200,
        )
        attempt = StageAttempt(
            stage=TaskStage.PLAN_REVIEW,
            attempt_index=2,
            proposer_agent_id="planner-a",
            reviewer_agent_id="reviewer-b",
            arbiter_agent_id="arbiter-c",
            input_artifact_ids=("art-1",),
            output_artifact_ids=("art-2",),
            outcome=TaskOutcome.NEEDS_REVISION,
            decision_reason="reviewer requested more detail",
        )

        self.assertEqual(review.to_dict()["decision"], "revise")
        self.assertEqual(attempt.to_dict()["stage"], "plan_review")
        self.assertEqual(attempt.to_dict()["outcome"], "needs_revision")

    def test_source_record_and_task_response_sources_serialize(self):
        from freemad.tasks.models import SourceRecord, TaskResponse
        from freemad.types import TaskRole, TaskStage

        source = SourceRecord(
            title="FREE-MAD paper",
            url="https://arxiv.org/html/2509.11035v1",
            summary="Consensus-free debate with trajectory-based scoring.",
        )
        response = TaskResponse(
            agent_id="researcher-a",
            stage=TaskStage.RESEARCH,
            role=TaskRole.RESEARCHER,
            content="Research bundle",
            sources=(source,),
        )

        self.assertEqual(
            source.to_dict(),
            {
                "title": "FREE-MAD paper",
                "url": "https://arxiv.org/html/2509.11035v1",
                "summary": "Consensus-free debate with trajectory-based scoring.",
            },
        )
        self.assertEqual(response.to_dict()["sources"], [source.to_dict()])

    def test_task_snapshot_request_and_response_serialize_nested_values(self):
        from freemad.tasks.models import (
            ArtifactRef,
            TaskRequest,
            TaskResponse,
            TaskSnapshot,
            WorkItem,
        )
        from freemad.types import (
            ActionKind,
            ArtifactKind,
            ReviewDecision,
            TaskRole,
            TaskStage,
            TaskStatus,
            TaskType,
            WorkItemStatus,
        )

        artifact = ArtifactRef(
            artifact_id="art-plan",
            task_id="task-1",
            stage=TaskStage.DRAFT_PLAN,
            kind=ArtifactKind.PLAN,
            path="artifacts/task-1/plan.md",
            created_by_agent_id="planner-a",
            created_ts_ms=100,
        )
        work_item = WorkItem(
            work_item_id="w-1",
            task_id="task-1",
            title="Implement config surface",
            description="Modify config and tests.",
            write_scope=("freemad/config.py",),
            verification_scope=("tests/pkg_mad/config/test_config.py",),
            status=WorkItemStatus.QUEUED,
            author_agent_id="implementer-a",
            reviewer_agent_id="reviewer-b",
        )
        snapshot = TaskSnapshot(
            task_id="task-1",
            goal="Add autonomous task runtime",
            task_type=TaskType.CODE,
            status=TaskStatus.RUNNING,
            current_stage=TaskStage.EXECUTE,
            workspace_root="/repo",
            iteration=3,
            stage_attempts=(),
            artifacts=(artifact,),
            work_items=(work_item,),
        )
        request = TaskRequest(
            task_id="task-1",
            goal="Add autonomous task runtime",
            stage=TaskStage.EXECUTE,
            role=TaskRole.IMPLEMENTER,
            workspace_root="/repo",
            allowed_actions=(ActionKind.WRITE_FILE, ActionKind.RUN_COMMAND),
            artifact_refs=(artifact,),
            work_item=work_item,
        )
        response = TaskResponse(
            agent_id="implementer-a",
            stage=TaskStage.CODE_REVIEW,
            role=TaskRole.REVIEWER,
            content="Patch needs tests.",
            review_decision=ReviewDecision.REVISE,
            findings=("missing tests",),
            commands=("pytest -q tests/pkg_mad/config/test_config.py",),
        )

        self.assertEqual(snapshot.to_dict()["task_type"], "code")
        self.assertEqual(snapshot.to_dict()["status"], "running")
        self.assertEqual(request.to_dict()["allowed_actions"], ["write_file", "run_command"])
        self.assertEqual(request.to_dict()["work_item"]["status"], "queued")
        self.assertEqual(response.to_dict()["review_decision"], "revise")
        self.assertEqual(response.to_dict()["commands"], ["pytest -q tests/pkg_mad/config/test_config.py"])

    def test_task_event_to_dict_serializes_optional_fields(self):
        from freemad.task_events import TaskEvent
        from freemad.types import ArtifactKind, ReviewDecision, TaskEventKind, TaskRole, TaskStage, TaskStatus

        event = TaskEvent(
            kind=TaskEventKind.REVIEW_RECORDED,
            task_id="task-1",
            ts_ms=999,
            stage=TaskStage.CODE_REVIEW,
            role=TaskRole.REVIEWER,
            status=TaskStatus.RUNNING,
            artifact_id="art-3",
            artifact_kind=ArtifactKind.REVIEW,
            work_item_id="w-1",
            review_decision=ReviewDecision.APPROVE,
            message="review complete",
        )

        self.assertEqual(
            event.to_dict(),
            {
                "kind": "review_recorded",
                "task_id": "task-1",
                "ts_ms": 999,
                "stage": "code_review",
                "role": "reviewer",
                "status": "running",
                "artifact_id": "art-3",
                "artifact_kind": "review",
                "work_item_id": "w-1",
                "review_decision": "approve",
                "message": "review complete",
            },
        )


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
