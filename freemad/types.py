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
