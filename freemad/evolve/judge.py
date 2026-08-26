from __future__ import annotations

import json
import math
import os
import shlex
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from freemad.config import (
    ComparatorTermConfig,
    Config,
    GatePredicateConfig,
    JudgeStageConfig,
)
from freemad.evolve.models import (
    GateFailure,
    JudgeStageResult,
    JudgeVerdict,
    ScoreVector,
)
from freemad.types import CompareDirection, GateOp, JudgeParseMode
from freemad.evolve.container import (
    build_argv,
    container_name,
    kill_container,
    require_runtime,
)
from freemad.evolve.sandbox import scrubbed_env
from freemad.utils.budget import enforce_size


STDOUT_EXCERPT_CHARS = 4000
STDERR_EXCERPT_CHARS = 4000


@dataclass(frozen=True)
class StageOutcome:
    result: JudgeStageResult
    ok: bool


def evaluate_gate(
    score: ScoreVector, gate: Sequence[GatePredicateConfig]
) -> Tuple[bool, Tuple[GateFailure, ...]]:
    """Pure gate evaluation. Missing components fail closed."""
    failures: List[GateFailure] = []
    for predicate in gate:
        actual = score.get(predicate.component)
        if actual is None:
            failures.append(
                GateFailure(
                    component=predicate.component,
                    op=predicate.op,
                    value=predicate.value,
                    actual=None,
                )
            )
            continue
        if not _compare(actual, predicate.op, predicate.value):
            failures.append(
                GateFailure(
                    component=predicate.component,
                    op=predicate.op,
                    value=predicate.value,
                    actual=actual,
                )
            )
    return (len(failures) == 0, tuple(failures))


_COMPARATORS = {
    GateOp.GTE: lambda a, b: a >= b,
    GateOp.GT: lambda a, b: a > b,
    GateOp.LTE: lambda a, b: a <= b,
    GateOp.LT: lambda a, b: a < b,
    GateOp.EQ: lambda a, b: a == b,
}


def _compare(actual: float, op: str, threshold: float) -> bool:
    try:
        return bool(_COMPARATORS[GateOp(op)](actual, threshold))
    except ValueError:
        raise ValueError(f"unsupported gate op: {op}") from None


def compare_scores(
    a: ScoreVector, b: ScoreVector, comparator: Sequence[ComparatorTermConfig]
) -> bool:
    """Return True iff `a` is strictly better than `b` under the lexicographic comparator.

    The first term whose difference exceeds its epsilon decides. Ties beyond the
    last term are NOT better (strict improvement required).
    """
    for term in comparator:
        av = a.get(term.component)
        bv = b.get(term.component)
        if av is None or bv is None:
            return False
        diff = av - bv
        if abs(diff) <= term.epsilon:
            continue
        if term.direction == CompareDirection.MAXIMIZE:
            return diff > 0
        return diff < 0
    return False


def compare_scores_detail(
    a: ScoreVector, b: ScoreVector, comparator: Sequence[ComparatorTermConfig]
) -> Tuple[bool, Optional[str]]:
    """Like `compare_scores`, but also reports which term decided and why.

    Mirrors `within_regress_bounds`'s return shape. `compare_scores` alone gives a
    rejected candidate no way to say *which* component fell short, so every
    `rejected_not_better` verdict ends up with an opaque `unknown` signature. This
    walks the same lexicographic comparator and returns the deciding term's
    candidate/incumbent values, diff, and epsilon as a diagnostic string.
    """
    for term in comparator:
        av = a.get(term.component)
        bv = b.get(term.component)
        if av is None or bv is None:
            return (False, f"component '{term.component}' missing during comparison")
        diff = av - bv
        if abs(diff) <= term.epsilon:
            continue
        better = diff > 0 if term.direction == CompareDirection.MAXIMIZE else diff < 0
        return (
            better,
            (
                f"component '{term.component}': candidate={av:.6g} incumbent={bv:.6g} "
                f"diff={diff:.6g} epsilon={term.epsilon:.6g}"
            ),
        )
    return (False, "no comparator term exceeded its epsilon (tie within bounds)")


def within_regress_bounds(
    candidate: ScoreVector,
    best_ever: ScoreVector,
    comparator: Sequence[ComparatorTermConfig],
) -> Tuple[bool, Optional[str]]:
    """True iff no component regresses beyond max_regress versus the best-ever score.

    `compare_scores` only reads terms up to the one that decides, so on its own it lets
    a candidate improve the deciding term while destroying every term below it. This is
    the floor that stops that: each component must stay within max_regress (default: the
    term's epsilon) of the best score the run has actually reached.
    """
    for term in comparator:
        cv = candidate.get(term.component)
        ev = best_ever.get(term.component)
        if cv is None or ev is None:
            return (
                False,
                f"component '{term.component}' missing during regression check",
            )
        limit = term.epsilon if term.max_regress is None else term.max_regress
        maximizing = term.direction == CompareDirection.MAXIMIZE
        allowed_worst = ev - limit if maximizing else ev + limit
        violated = cv < allowed_worst if maximizing else cv > allowed_worst
        if violated:
            return (
                False,
                (
                    f"component '{term.component}' regressed past bound: "
                    f"{cv} vs floor {allowed_worst} (best-ever {ev})"
                ),
            )
    return (True, None)


def target_met(score: ScoreVector, target: Sequence[GatePredicateConfig]) -> bool:
    """True iff a goal-met test is configured and the score satisfies it.

    An empty target is "no goal-met test", not "the goal is met". `evaluate_gate` is
    vacuously true on an empty predicate list -- correct for `judge.gate`, where no
    predicates means nothing to block admission, but catastrophic here: it would end
    every run at the baseline with zero iterations.
    """
    if not target:
        return False
    met, _ = evaluate_gate(score, target)
    return met


def parse_stage_stdout(raw_stdout: str, provides: Sequence[str]) -> Dict[str, float]:
    """Fail-closed parse of a json_stdout stage.

    Requires exactly {"components": {...}} with finite float values for every
    declared component. Any deviation raises ValueError.
    """
    data = json.loads(raw_stdout)
    if not isinstance(data, dict):
        raise ValueError("stage stdout must be a JSON object")
    components_raw = data.get("components")
    if not isinstance(components_raw, dict):
        raise ValueError("stage stdout must contain a 'components' object")
    parsed: Dict[str, float] = {}
    for name in provides:
        if name not in components_raw:
            raise ValueError(f"declared component '{name}' missing from stage output")
        value = components_raw[name]
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError(f"component '{name}' must be a number")
        value_f = float(value)
        if not math.isfinite(value_f):
            raise ValueError(f"component '{name}' must be finite")
        parsed[name] = value_f
    return parsed


class Judge:
    """Executes judge stages in a worktree and produces a verdict."""

    def __init__(self, cfg: Config):
        self._cfg = cfg

    def judge_worktree(self, worktree_path: Path) -> JudgeVerdict:
        evolve = self._cfg.evolve
        if evolve.judge.container.enabled:
            # Up front, once per judging: a missing runtime must stop the run rather than
            # quietly execute worker-authored code on the host.
            require_runtime(evolve.judge.container)
        stage_results: List[JudgeStageResult] = []
        components: Dict[str, float] = {}
        failed_stage: Optional[str] = None
        failure_detail = ""

        for stage in evolve.judge.stages:
            outcome = self._run_stage(stage, worktree_path)
            stage_results.append(outcome.result)
            if not outcome.ok:
                failed_stage = stage.name
                failure_detail = (
                    outcome.result.stderr_excerpt or outcome.result.stdout_excerpt
                )
                break
            components.update(outcome.result.parsed_components)

        score = ScoreVector(components=dict(components))
        gate_passed, gate_failures = evaluate_gate(score, evolve.judge.gate)
        return JudgeVerdict(
            stage_results=tuple(stage_results),
            score=score,
            gate_passed=gate_passed,
            gate_failures=gate_failures,
            protected_hashes={},
            failed_stage=failed_stage,
            failure_detail=enforce_size(
                failure_detail, STDERR_EXCERPT_CHARS, "judge_failure_detail"
            )[0],
        )

    def _run_stage(self, stage: JudgeStageConfig, worktree_path: Path) -> StageOutcome:
        # shlex, not str.split: `pytest -k "not slow"` is a single argument.
        cmd = shlex.split(stage.command)
        judge = self._cfg.evolve.judge
        env = scrubbed_env(judge.env_passthrough, network=judge.network)

        name: Optional[str] = None
        if judge.container.enabled:
            name = container_name()
            argv = build_argv(
                judge.container,
                cmd,
                worktree_path,
                env,
                network=judge.network,
                name=name,
                uid_gid=(
                    f"{os.getuid()}:{os.getgid()}" if hasattr(os, "getuid") else None
                ),
            )
            # The container carries its own environment and working directory.
            run_kwargs: Dict[str, Any] = {}
        else:
            argv = cmd
            run_kwargs = {"cwd": str(worktree_path), "env": env}

        timed_out = False
        exit_code: Optional[int] = None
        stdout_text = ""
        stderr_text = ""
        try:
            completed = subprocess.run(  # noqa: S603 - fixed argv from validated config
                argv,
                text=True,
                capture_output=True,
                timeout=stage.timeout_sec,
                check=False,
                **run_kwargs,
            )
            exit_code = completed.returncode
            stdout_text = completed.stdout or ""
            stderr_text = completed.stderr or ""
        except subprocess.TimeoutExpired as exc:
            timed_out = True
            if name is not None:
                # `timeout` reaps the client only; the container would keep running and
                # hold the bind-mounted worktree open.
                kill_container(judge.container.runtime, name)
            stdout_text = (exc.stdout or "") if isinstance(exc.stdout, str) else ""
            stderr_text = (exc.stderr or "") if isinstance(exc.stderr, str) else ""
            stderr_text = stderr_text or f"stage timed out after {stage.timeout_sec}s"
        except OSError as exc:
            timed_out = False
            exit_code = None
            stdout_text = ""
            stderr_text = f"stage could not start: {exc}"

        parsed: Dict[str, float] = {}
        ok = (not timed_out) and exit_code == 0
        parse_error: Optional[str] = None
        if ok and stage.parse == JudgeParseMode.JSON_STDOUT:
            try:
                parsed = parse_stage_stdout(stdout_text, stage.provides)
            except (ValueError, json.JSONDecodeError) as exc:
                ok = False
                parse_error = f"fail-closed parse error: {exc}"
                stderr_text = stderr_text or parse_error

        return StageOutcome(
            result=JudgeStageResult(
                name=stage.name,
                command=stage.command,
                parse=stage.parse,
                exit_code=exit_code,
                timed_out=timed_out,
                stdout_excerpt=enforce_size(
                    stdout_text, STDOUT_EXCERPT_CHARS, "judge_stdout"
                )[0],
                stderr_excerpt=enforce_size(
                    stderr_text, STDERR_EXCERPT_CHARS, "judge_stderr"
                )[0],
                parsed_components=parsed,
            ),
            ok=ok,
        )


def compute_manifest_hash(goal: str, judge_cfg: Mapping[str, object]) -> str:
    """The manifest is the goal plus the judge definition: what "better" means."""
    import hashlib

    canonical = json.dumps({"goal": goal, "judge": dict(judge_cfg)}, sort_keys=True)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
