import tempfile
import unittest
from pathlib import Path


class TestTaskStore(unittest.TestCase):
    def test_create_task_persists_initial_snapshot(self):
        from freemad.tasks.store import TaskStore
        from freemad.types import TaskStage, TaskStatus, TaskType

        with tempfile.TemporaryDirectory() as tmp:
            store = TaskStore(Path(tmp) / "tasks.db", Path(tmp) / "artifacts")
            task = store.create_task(
                goal="Solidify the plan.",
                task_type=TaskType.PLAN,
                workspace_root="/repo",
            )

            reloaded = store.get_task(task.task_id)

            self.assertIsNotNone(reloaded)
            assert reloaded is not None
            self.assertEqual(reloaded.goal, "Solidify the plan.")
            self.assertEqual(reloaded.task_type, TaskType.PLAN)
            self.assertEqual(reloaded.status, TaskStatus.PENDING)
            self.assertEqual(reloaded.current_stage, TaskStage.INTAKE)
            self.assertEqual(reloaded.workspace_root, "/repo")
            store.close()

    def test_append_event_and_list_events_preserve_order(self):
        from freemad.task_events import TaskEvent
        from freemad.tasks.store import TaskStore
        from freemad.types import TaskEventKind, TaskRole, TaskStage, TaskType

        with tempfile.TemporaryDirectory() as tmp:
            store = TaskStore(Path(tmp) / "tasks.db", Path(tmp) / "artifacts")
            task = store.create_task("Track events", TaskType.PLAN, "/repo")

            store.append_event(
                TaskEvent(
                    kind=TaskEventKind.STAGE_STARTED,
                    task_id=task.task_id,
                    ts_ms=10,
                    stage=TaskStage.RESEARCH,
                    role=TaskRole.RESEARCHER,
                )
            )
            store.append_event(
                TaskEvent(
                    kind=TaskEventKind.HUMAN_INPUT_REQUESTED,
                    task_id=task.task_id,
                    ts_ms=20,
                    stage=TaskStage.DRAFT_PLAN,
                    message="Clarify success criteria.",
                )
            )

            events = store.list_events(task.task_id)

            self.assertEqual([event.kind.value for event in events], ["stage_started", "human_input_requested"])
            self.assertEqual(events[0].stage, TaskStage.RESEARCH)
            self.assertEqual(events[0].role, TaskRole.RESEARCHER)
            self.assertEqual(events[1].message, "Clarify success criteria.")
            store.close()

    def test_save_artifact_writes_content_and_registers_metadata(self):
        from freemad.tasks.store import TaskStore
        from freemad.types import ArtifactKind, TaskRole, TaskStage, TaskType

        with tempfile.TemporaryDirectory() as tmp:
            store = TaskStore(Path(tmp) / "tasks.db", Path(tmp) / "artifacts")
            task = store.create_task("Save a plan", TaskType.PLAN, "/repo")

            artifact = store.save_artifact(
                task.task_id,
                kind=ArtifactKind.PLAN,
                stage=TaskStage.DRAFT_PLAN,
                content="# Plan\n",
                created_by_agent_id="planner-a",
                role=TaskRole.PLANNER,
                summary="first plan",
            )

            self.assertTrue(Path(artifact.path).exists())
            self.assertEqual(Path(artifact.path).read_text(encoding="utf-8"), "# Plan\n")
            artifacts = store.list_artifacts(task.task_id)
            self.assertEqual(len(artifacts), 1)
            self.assertEqual(artifacts[0].kind, ArtifactKind.PLAN)
            self.assertEqual(artifacts[0].role, TaskRole.PLANNER)
            self.assertEqual(artifacts[0].summary, "first plan")
            store.close()

    def test_task_state_and_work_items_round_trip_after_reopen(self):
        from freemad.tasks.models import StageAttempt, TaskSnapshot, WorkItem
        from freemad.tasks.store import TaskStore
        from freemad.types import TaskOutcome, TaskStage, TaskStatus, TaskType, WorkItemStatus

        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "tasks.db"
            artifacts_dir = Path(tmp) / "artifacts"
            store = TaskStore(db_path, artifacts_dir)
            task = store.create_task("Implement task runtime", TaskType.CODE, "/repo")
            attempt = StageAttempt(
                stage=TaskStage.PLAN_REVIEW,
                attempt_index=1,
                proposer_agent_id="planner-a",
                reviewer_agent_id="reviewer-b",
                outcome=TaskOutcome.APPROVED,
                output_artifact_ids=("art-plan-1",),
                decision_reason="Plan approved.",
            )
            work_item = WorkItem(
                work_item_id="w-1",
                task_id=task.task_id,
                title="Add task store",
                description="Create the SQLite persistence layer.",
                write_scope=("freemad/tasks/store.py",),
                verification_scope=("tests/pkg_mad/tasks/test_store.py",),
                status=WorkItemStatus.IN_PROGRESS,
                author_agent_id="implementer-a",
                reviewer_agent_id="reviewer-b",
            )
            updated = TaskSnapshot(
                task_id=task.task_id,
                goal=task.goal,
                task_type=task.task_type,
                status=TaskStatus.RUNNING,
                current_stage=TaskStage.EXECUTE,
                workspace_root=task.workspace_root,
                iteration=2,
                stage_attempts=(attempt,),
                work_items=(work_item,),
            )

            store.update_task(updated)
            store.save_work_items(task.task_id, (work_item,))
            store.close()

            reopened = TaskStore(db_path, artifacts_dir)
            reloaded = reopened.get_task(task.task_id)
            work_items = reopened.list_work_items(task.task_id)

            self.assertIsNotNone(reloaded)
            assert reloaded is not None
            self.assertEqual(reloaded.status, TaskStatus.RUNNING)
            self.assertEqual(reloaded.current_stage, TaskStage.EXECUTE)
            self.assertEqual(reloaded.iteration, 2)
            self.assertEqual(len(reloaded.stage_attempts), 1)
            self.assertEqual(reloaded.stage_attempts[0].outcome, TaskOutcome.APPROVED)
            self.assertEqual(len(work_items), 1)
            self.assertEqual(work_items[0].status, WorkItemStatus.IN_PROGRESS)
            self.assertEqual(work_items[0].write_scope, ("freemad/tasks/store.py",))
            reopened.close()


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
