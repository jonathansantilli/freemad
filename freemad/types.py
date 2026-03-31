from __future__ import annotations
import sys
from enum import Enum

# StrEnum was added in Python 3.11
if sys.version_info >= (3, 11):
    from enum import StrEnum
else:
    class StrEnum(str, Enum):  # type: ignore[no-redef]
        """Compatibility StrEnum for Python 3.10"""
        pass


class Decision(StrEnum):
    KEEP = "KEEP"
    REVISE = "REVISE"


class RoundType(StrEnum):
    GENERATION = "generation"
    CRITIQUE = "critique"


class ScoreAction(StrEnum):
    INITIAL = "initial"
    KEEP = "keep"
    CHANGE = "change"


class TieBreak(StrEnum):
    DETERMINISTIC = "deterministic"
    RANDOM = "random"


class GenMarker(StrEnum):
    SOLUTION = "SOLUTION"
    REASONING = "REASONING"


class CritMarker(StrEnum):
    DECISION = "DECISION"
    REVISED_SOLUTION = "REVISED_SOLUTION"
    REASONING = "REASONING"


class ValidatorName(StrEnum):
    SYNTAX = "syntax"
    SANDBOX = "sandbox"
    SECURITY = "security"
    COVERAGE = "coverage"


class LogEvent(StrEnum):
    RUN_START = "run_start"
    RUN_END = "run_end"
    ROUND_START = "round_start"
    ROUND_END = "round_end"
    DEADLINE_SOFT = "deadline_hit_soft"
    DEADLINE_HARD = "deadline_hit_hard"
    TRUNCATE = "truncate"
    BUDGET_EXCEEDED = "budget_exceeded"
    VALIDATION_DONE = "validation_done"
    HEALTH_STATUS = "health_status"
    COMMAND = "command"


class RunEventKind(StrEnum):
    RUN_STARTED = "run_started"
    RUN_COMPLETED = "run_completed"
    RUN_FAILED = "run_failed"
    RUN_BUDGET_EXCEEDED = "run_budget_exceeded"
    ROUND_STARTED = "round_started"
    ROUND_COMPLETED = "round_completed"
    AGENT_GENERATE_STARTED = "agent_generate_started"
    AGENT_GENERATE_FINISHED = "agent_generate_finished"
    AGENT_CRITIQUE_STARTED = "agent_critique_started"
    AGENT_CRITIQUE_FINISHED = "agent_critique_finished"
    SCORES_UPDATED = "scores_updated"
    FINAL_ANSWER_SELECTED = "final_answer_selected"


class RuntimeMode(StrEnum):
    DEBATE = "debate"
    AUTONOMOUS = "autonomous"


class TaskType(StrEnum):
    PLAN = "plan"
    CODE = "code"


class TaskRole(StrEnum):
    RESEARCHER = "researcher"
    PLANNER = "planner"
    REVIEWER = "reviewer"
    IMPLEMENTER = "implementer"
    VERIFIER = "verifier"
    ARBITER = "arbiter"


class TaskStage(StrEnum):
    INTAKE = "intake"
    RESEARCH = "research"
    DRAFT_PLAN = "draft_plan"
    PLAN_REVIEW = "plan_review"
    EXECUTE = "execute"
    CODE_REVIEW = "code_review"
    VERIFY = "verify"
    FINALIZE = "finalize"


class TaskOutcome(StrEnum):
    APPROVED = "approved"
    REJECTED = "rejected"
    NEEDS_REVISION = "needs_revision"
    NEEDS_HUMAN = "needs_human"
    BLOCKED = "blocked"
    BUDGET_EXHAUSTED = "budget_exhausted"


class ActionKind(StrEnum):
    RESEARCH = "research"
    PLAN = "plan"
    REVIEW = "review"
    IMPLEMENT = "implement"
    VERIFY = "verify"
    WRITE_FILE = "write_file"
    RUN_COMMAND = "run_command"


class ReviewDecision(StrEnum):
    APPROVE = "approve"
    REVISE = "revise"
    REJECT = "reject"


class TaskStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    WAITING_FOR_HUMAN = "waiting_for_human"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class ArtifactKind(StrEnum):
    TASK_BRIEF = "task_brief"
    QUESTION_SET = "question_set"
    RESEARCH_BUNDLE = "research_bundle"
    SOURCE_BUNDLE = "source_bundle"
    PLAN = "plan"
    RISK_REGISTER = "risk_register"
    WORK_ITEM = "work_item"
    PATCH = "patch"
    REVIEW = "review"
    VERIFICATION_REPORT = "verification_report"
    DECISION_RECORD = "decision_record"
    FINAL_SUMMARY = "final_summary"


class WorkItemStatus(StrEnum):
    QUEUED = "queued"
    IN_PROGRESS = "in_progress"
    IN_REVIEW = "in_review"
    CHANGES_REQUESTED = "changes_requested"
    APPROVED = "approved"
    VERIFIED = "verified"
    BLOCKED = "blocked"


class TaskEventKind(StrEnum):
    TASK_CREATED = "task_created"
    TASK_STARTED = "task_started"
    STAGE_STARTED = "stage_started"
    ARTIFACT_CREATED = "artifact_created"
    REVIEW_RECORDED = "review_recorded"
    DECISION_RECORDED = "decision_recorded"
    STAGE_RETRIED = "stage_retried"
    ARBITER_REQUESTED = "arbiter_requested"
    HUMAN_INPUT_REQUESTED = "human_input_requested"
    HUMAN_INPUT_RECEIVED = "human_input_received"
    WORK_ITEM_CREATED = "work_item_created"
    WORK_ITEM_STARTED = "work_item_started"
    WORK_ITEM_COMPLETED = "work_item_completed"
    VERIFICATION_STARTED = "verification_started"
    VERIFICATION_COMPLETED = "verification_completed"
    TASK_PAUSED = "task_paused"
    TASK_RESUMED = "task_resumed"
    TASK_COMPLETED = "task_completed"
    TASK_FAILED = "task_failed"
