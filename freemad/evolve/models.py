from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Optional, Tuple

from freemad.types import (
    EvolveEventKind,
    EvolveRunStatus,
    IterationOutcome,
    SupervisorCause,
    VariationKind,
)


@dataclass(frozen=True)
class ScoreVector:
    components: Dict[str, float] = field(default_factory=dict)

    def get(self, component: str, default: Optional[float] = None) -> Optional[float]:
        return self.components.get(component, default)

    def to_dict(self) -> Dict[str, float]:
        return dict(self.components)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ScoreVector":
        return cls(components={str(k): float(v) for k, v in dict(data).items()})


@dataclass(frozen=True)
class GateFailure:
    component: str
    op: str
    value: float
    actual: Optional[float]

    def describe(self) -> str:
        if self.actual is None:
            return f"{self.component}: missing (required {self.op} {self.value})"
        return f"{self.component}: {self.actual} not {self.op} {self.value}"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "component": self.component,
            "op": self.op,
            "value": self.value,
            "actual": self.actual,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "GateFailure":
        actual = data.get("actual")
        return cls(
            component=str(data["component"]),
            op=str(data["op"]),
            value=float(data["value"]),
            actual=(float(actual) if actual is not None else None),
        )


@dataclass(frozen=True)
class JudgeStageResult:
    name: str
    command: str
    parse: str
    exit_code: Optional[int] = None
    timed_out: bool = False
    stdout_excerpt: str = ""
    stderr_excerpt: str = ""
    parsed_components: Dict[str, float] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "command": self.command,
            "parse": self.parse,
            "exit_code": self.exit_code,
            "timed_out": self.timed_out,
            "stdout_excerpt": self.stdout_excerpt,
            "stderr_excerpt": self.stderr_excerpt,
            "parsed_components": dict(self.parsed_components),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "JudgeStageResult":
        return cls(
            name=str(data["name"]),
            command=str(data.get("command", "")),
            parse=str(data.get("parse", "")),
            exit_code=(
                int(data["exit_code"]) if data.get("exit_code") is not None else None
            ),
            timed_out=bool(data.get("timed_out", False)),
            stdout_excerpt=str(data.get("stdout_excerpt", "")),
            stderr_excerpt=str(data.get("stderr_excerpt", "")),
            parsed_components={
                str(k): float(v)
                for k, v in dict(data.get("parsed_components", {})).items()
            },
        )


@dataclass(frozen=True)
class JudgeVerdict:
    stage_results: Tuple[JudgeStageResult, ...] = ()
    score: Optional[ScoreVector] = None
    gate_passed: bool = False
    gate_failures: Tuple[GateFailure, ...] = ()
    protected_hashes: Dict[str, str] = field(default_factory=dict)
    failed_stage: Optional[str] = None
    failure_detail: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "stage_results": [r.to_dict() for r in self.stage_results],
            "score": (self.score.to_dict() if self.score is not None else None),
            "gate_passed": self.gate_passed,
            "gate_failures": [f.to_dict() for f in self.gate_failures],
            "protected_hashes": dict(self.protected_hashes),
            "failed_stage": self.failed_stage,
            "failure_detail": self.failure_detail,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "JudgeVerdict":
        score_raw = data.get("score")
        return cls(
            stage_results=tuple(
                JudgeStageResult.from_dict(d)
                for d in list(data.get("stage_results", []))
            ),
            score=(ScoreVector.from_dict(score_raw) if score_raw is not None else None),
            gate_passed=bool(data.get("gate_passed", False)),
            gate_failures=tuple(
                GateFailure.from_dict(d) for d in list(data.get("gate_failures", []))
            ),
            protected_hashes={
                str(k): str(v)
                for k, v in dict(data.get("protected_hashes", {})).items()
            },
            failed_stage=(
                str(data["failed_stage"]) if data.get("failed_stage") else None
            ),
            failure_detail=str(data.get("failure_detail", "")),
        )


@dataclass(frozen=True)
class VariationResult:
    kind: VariationKind
    agent_ids: Tuple[str, ...] = ()
    produced_changes: bool = False
    diff_stat: str = ""
    self_report: str = ""
    final_output: str = ""
    worker_error: Optional[str] = None
    transcript_ref: Optional[str] = None
    duration_ms: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "kind": self.kind.value,
            "agent_ids": list(self.agent_ids),
            "produced_changes": self.produced_changes,
            "diff_stat": self.diff_stat,
            "self_report": self.self_report,
            "final_output": self.final_output,
            "worker_error": self.worker_error,
            "transcript_ref": self.transcript_ref,
            "duration_ms": self.duration_ms,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "VariationResult":
        return cls(
            kind=VariationKind(str(data["kind"])),
            agent_ids=tuple(str(x) for x in list(data.get("agent_ids", []))),
            produced_changes=bool(data.get("produced_changes", False)),
            diff_stat=str(data.get("diff_stat", "")),
            self_report=str(data.get("self_report", "")),
            final_output=str(data.get("final_output", "")),
            worker_error=(
                str(data["worker_error"]) if data.get("worker_error") else None
            ),
            transcript_ref=(
                str(data["transcript_ref"]) if data.get("transcript_ref") else None
            ),
            duration_ms=int(data.get("duration_ms", 0)),
        )


@dataclass(frozen=True)
class IterationRecord:
    iteration: int
    kind: VariationKind
    outcome: IterationOutcome
    score: Optional[ScoreVector] = None
    sha: Optional[str] = None
    tag: Optional[str] = None
    failure_signature: Optional[str] = None
    self_report: Optional[str] = None
    started_at_ms: int = 0
    duration_ms: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "iteration": self.iteration,
            "kind": self.kind.value,
            "outcome": self.outcome.value,
            "score": (self.score.to_dict() if self.score is not None else None),
            "sha": self.sha,
            "tag": self.tag,
            "failure_signature": self.failure_signature,
            "self_report": self.self_report,
            "started_at_ms": self.started_at_ms,
            "duration_ms": self.duration_ms,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "IterationRecord":
        score_raw = data.get("score")
        return cls(
            iteration=int(data["iteration"]),
            kind=VariationKind(str(data["kind"])),
            outcome=IterationOutcome(str(data["outcome"])),
            score=(ScoreVector.from_dict(score_raw) if score_raw is not None else None),
            sha=(str(data["sha"]) if data.get("sha") else None),
            tag=(str(data["tag"]) if data.get("tag") else None),
            failure_signature=(
                str(data["failure_signature"])
                if data.get("failure_signature")
                else None
            ),
            self_report=(str(data["self_report"]) if data.get("self_report") else None),
            started_at_ms=int(data.get("started_at_ms", 0)),
            duration_ms=int(data.get("duration_ms", 0)),
        )


@dataclass(frozen=True)
class SupervisorDirective:
    directive_id: str
    text: str
    source_ref: str
    cause: SupervisorCause
    created_iteration: int
    ttl_iterations: int

    def expired(self, current_iteration: int) -> bool:
        return current_iteration > self.created_iteration + self.ttl_iterations

    def to_dict(self) -> Dict[str, Any]:
        return {
            "directive_id": self.directive_id,
            "text": self.text,
            "source_ref": self.source_ref,
            "cause": self.cause.value,
            "created_iteration": self.created_iteration,
            "ttl_iterations": self.ttl_iterations,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "SupervisorDirective":
        return cls(
            directive_id=str(data["directive_id"]),
            text=str(data["text"]),
            source_ref=str(data.get("source_ref", "")),
            cause=SupervisorCause(str(data["cause"])),
            created_iteration=int(data["created_iteration"]),
            ttl_iterations=int(data["ttl_iterations"]),
        )


@dataclass(frozen=True)
class EvolveRunSnapshot:
    run_id: str
    goal: str
    manifest_hash: str
    status: EvolveRunStatus
    seed_ref: str
    run_branch: str
    repo_path: str
    iteration: int = 0
    best_iteration: Optional[int] = None
    best_sha: Optional[str] = None
    best_score: Optional[ScoreVector] = None
    baseline_score: Optional[ScoreVector] = None
    stop_reason: Optional[str] = None
    error: Optional[str] = None
    interventions_without_new_best: int = 0
    created_at_ms: int = 0
    updated_at_ms: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "run_id": self.run_id,
            "goal": self.goal,
            "manifest_hash": self.manifest_hash,
            "status": self.status.value,
            "seed_ref": self.seed_ref,
            "run_branch": self.run_branch,
            "repo_path": self.repo_path,
            "iteration": self.iteration,
            "best_iteration": self.best_iteration,
            "best_sha": self.best_sha,
            "best_score": (
                self.best_score.to_dict() if self.best_score is not None else None
            ),
            "baseline_score": (
                self.baseline_score.to_dict()
                if self.baseline_score is not None
                else None
            ),
            "stop_reason": self.stop_reason,
            "error": self.error,
            "interventions_without_new_best": self.interventions_without_new_best,
            "created_at_ms": self.created_at_ms,
            "updated_at_ms": self.updated_at_ms,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "EvolveRunSnapshot":
        best_raw = data.get("best_score")
        baseline_raw = data.get("baseline_score")
        return cls(
            run_id=str(data["run_id"]),
            goal=str(data["goal"]),
            manifest_hash=str(data["manifest_hash"]),
            status=EvolveRunStatus(str(data["status"])),
            seed_ref=str(data["seed_ref"]),
            run_branch=str(data["run_branch"]),
            repo_path=str(data["repo_path"]),
            iteration=int(data.get("iteration", 0)),
            best_iteration=(
                int(data["best_iteration"])
                if data.get("best_iteration") is not None
                else None
            ),
            best_sha=(str(data["best_sha"]) if data.get("best_sha") else None),
            best_score=(
                ScoreVector.from_dict(best_raw) if best_raw is not None else None
            ),
            baseline_score=(
                ScoreVector.from_dict(baseline_raw)
                if baseline_raw is not None
                else None
            ),
            stop_reason=(str(data["stop_reason"]) if data.get("stop_reason") else None),
            error=(str(data["error"]) if data.get("error") else None),
            interventions_without_new_best=int(
                data.get("interventions_without_new_best", 0)
            ),
            created_at_ms=int(data.get("created_at_ms", 0)),
            updated_at_ms=int(data.get("updated_at_ms", 0)),
        )


@dataclass(frozen=True)
class EvolveEvent:
    seq: Optional[int]
    run_id: str
    ts_ms: int
    iteration: int
    kind: EvolveEventKind
    payload: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "seq": self.seq,
            "run_id": self.run_id,
            "ts_ms": self.ts_ms,
            "iteration": self.iteration,
            "kind": self.kind.value,
            "payload": dict(self.payload),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "EvolveEvent":
        raw_seq = data.get("seq")
        return cls(
            seq=(int(raw_seq) if raw_seq is not None else None),
            run_id=str(data["run_id"]),
            ts_ms=int(data["ts_ms"]),
            iteration=int(data["iteration"]),
            kind=EvolveEventKind(str(data["kind"])),
            payload=dict(data.get("payload") or {}),
        )
