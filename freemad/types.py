from __future__ import annotations
from enum import StrEnum


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
