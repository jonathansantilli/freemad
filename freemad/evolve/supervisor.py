from __future__ import annotations

import json
from dataclasses import dataclass
from typing import List, Optional, Sequence, Tuple

from freemad.config import Config
from freemad.evolve.context import ContextInput, generate_context
from freemad.evolve.models import IterationRecord, ScoreVector, SupervisorDirective
from freemad.evolve.variation import scope_debate_agents, scope_debate_budget
from freemad.prompts.evolve import build_supervisor_requirement
from freemad.utils.budget import enforce_size
from freemad.types import IterationOutcome, SupervisorCause, SupervisorIntervention


@dataclass(frozen=True)
class SupervisorFinding:
    cause: SupervisorCause
    detail: str


@dataclass(frozen=True)
class InterventionResult:
    directives: Tuple[SupervisorDirective, ...]
    transcript_ref: Optional[str]
    error: Optional[str]


def detect_stall(
    records: Sequence[IterationRecord],
    current_iteration: int,
    window: int,
    since_iteration: int = -1,
) -> bool:
    """No commit within the last `window` completed iterations.

    `since_iteration` implements evolve.md section 3's "reset counters after
    intervention": evidence from before the last course correction must not re-trigger
    it, or the run reaches WAITING_FOR_HUMAN about twice as fast as configured.
    """
    completed = [
        r for r in records if since_iteration < r.iteration < current_iteration
    ]
    recent = completed[-window:] if window > 0 else []
    if len(recent) < window:
        return False
    return all(r.outcome != IterationOutcome.COMMITTED for r in recent)


def detect_loop(
    records: Sequence[IterationRecord], threshold: int, since_iteration: int = -1
) -> Optional[str]:
    """`threshold` consecutive rejections sharing one failure signature.

    Bounded below by `since_iteration` for the same reason as `detect_stall`.
    """
    consecutive: List[IterationRecord] = []
    for record in reversed([r for r in records if r.iteration > since_iteration]):
        # Any non-commit counts. A run wedged on WORKER_FAILED — a misconfigured
        # operator, or an agent that keeps producing nothing — was invisible here no
        # matter how many identical failures it stacked up.
        if record.outcome != IterationOutcome.COMMITTED:
            consecutive.append(record)
        else:
            break
    if len(consecutive) < threshold:
        return None
    head = consecutive[0].failure_signature or "unknown"
    for record in consecutive[:threshold]:
        if (record.failure_signature or "unknown") != head:
            return None
    return head


class Supervisor:
    """Read-only course-corrector: detects drift, runs debates for directions.

    The supervisor never touches the worktree, never reads or alters the judge,
    and cannot halt the run. Failures inside an intervention are logged and the
    run continues.
    """

    def __init__(self, cfg: Config):
        self._cfg = cfg

    def detect(
        self,
        records: Sequence[IterationRecord],
        current_iteration: int,
        last_intervention_iteration: int,
        cooldown_iterations: int,
    ) -> Optional[SupervisorFinding]:
        if last_intervention_iteration >= 0 and (
            current_iteration - last_intervention_iteration
            < max(1, cooldown_iterations)
        ):
            return None
        sup = self._cfg.evolve.supervisor
        loop_sig = detect_loop(records, sup.loop_threshold, last_intervention_iteration)
        if loop_sig is not None:
            return SupervisorFinding(
                cause=SupervisorCause.LOOP,
                detail=f"loop: {sup.loop_threshold} consecutive rejections with signature '{loop_sig}'",
            )
        if detect_stall(
            records, current_iteration, sup.stall_window, last_intervention_iteration
        ):
            return SupervisorFinding(
                cause=SupervisorCause.STALL,
                detail=f"stall: no commit in the last {sup.stall_window} iterations",
            )
        return None

    def intervene(  # noqa: PLR0913 - the supervisor needs the whole run picture
        self,
        snapshot_goal: str,
        records: Sequence[IterationRecord],
        best_score: Optional[ScoreVector],
        baseline_score: Optional[ScoreVector],
        best_sha: Optional[str],
        finding: SupervisorFinding,
        active_directives: Sequence[str],
        debate_run_id: str,
        iteration: int,
    ) -> InterventionResult:
        context_doc = generate_context(
            ContextInput(
                goal=snapshot_goal,
                iteration=iteration,
                best_iteration=None,
                best_sha=best_sha,
                best_score=best_score,
                baseline_score=baseline_score,
                records=tuple(records),
                directives=tuple(active_directives),
            ),
            budget_chars=self._cfg.evolve.context_budget_chars,
        )
        requirement = build_supervisor_requirement(
            cause=finding.cause.value,
            detail=finding.detail,
            recent_failures=_recent_failures(records),
            context_doc=context_doc,
        )
        try:
            if (
                self._cfg.evolve.supervisor.intervention
                == SupervisorIntervention.SINGLE_AGENT
            ):
                result = self._ask_one_agent(requirement)
            else:
                result = self._run_debate(requirement)
            solution = str(result.get("final_solution", ""))
            directions = parse_directions(solution)
        except Exception as exc:  # noqa: BLE001 - supervisor failure must not halt the run
            return InterventionResult(
                directives=(),
                transcript_ref=None,
                error=enforce_size(str(exc), 500, "intervention_error")[0],
            )
        if not directions:
            return InterventionResult(
                directives=(),
                transcript_ref=None,
                error="debate produced no valid directions",
            )
        ref = save_intervention_transcript(self._cfg, debate_run_id, iteration, result)
        ttl = self._cfg.evolve.supervisor.directions_ttl_iterations
        directives = tuple(
            SupervisorDirective(
                directive_id=f"{debate_run_id}-d{iteration}-{i}",
                text=text,
                source_ref=ref or debate_run_id,
                cause=finding.cause,
                created_iteration=iteration,
                ttl_iterations=ttl,
            )
            for i, text in enumerate(directions)
        )
        return InterventionResult(directives=directives, transcript_ref=ref, error=None)

    def _run_debate(self, requirement: str) -> dict:
        from freemad.orchestrator import Orchestrator

        scoped = scope_debate_agents(scope_debate_budget(self._cfg, elapsed_sec=0.0))
        return Orchestrator(scoped).run(
            requirement, max_rounds=max(1, self._cfg.evolve.variation.debate_rounds)
        )

    def _ask_one_agent(self, requirement: str) -> dict:
        """Cheaper course-correction: ask one agent instead of running a whole debate.

        Shaped like a debate result so neither the caller nor the transcript writer has
        to care which mode produced the directions.
        """
        from freemad.agents.factory import AgentFactory

        agents = AgentFactory(self._cfg).build_all()
        wanted = self._cfg.evolve.variation.agent_id
        agent = agents.get(wanted) if wanted else None
        if agent is None:
            agent = next(iter(agents.values()), None)
        if agent is None:
            raise RuntimeError(
                "no enabled agent available for a single_agent intervention"
            )
        response = agent.generate(requirement)
        return {"final_solution": response.solution, "transcript": []}


def _recent_failures(records: Sequence[IterationRecord], limit: int = 6) -> str:
    rejected = [r for r in records if r.outcome != IterationOutcome.COMMITTED][-limit:]
    if not rejected:
        return "(none)"
    lines = [f"- it{r.iteration}: {r.failure_signature or 'unknown'}" for r in rejected]
    return "\n".join(lines)


def parse_directions(solution: str) -> List[str]:
    """Schema-validate a JSON directions proposal; empty list on any deviation."""
    text = solution.strip()
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end <= start:
        return []
    try:
        data = json.loads(text[start : end + 1])
    except json.JSONDecodeError:
        return []
    if not isinstance(data, dict):
        return []
    raw_directions = data.get("directions")
    if not isinstance(raw_directions, list):
        return []
    cleaned = [str(d).strip() for d in raw_directions if str(d).strip()]
    if not (3 <= len(cleaned) <= 5):
        return []
    return cleaned


def active_directives_of(
    candidates: Sequence[SupervisorDirective], current_iteration: int
) -> List[SupervisorDirective]:
    return [d for d in candidates if not d.expired(current_iteration)]


def save_intervention_transcript(
    cfg: Config, run_id: str, iteration: int, result: dict
) -> Optional[str]:
    """Persist the whole intervention, not just its conclusion.

    The directions are already in the `SUPERVISOR_DIRECTIONS` event; what this file is
    for is the reasoning behind them.
    """
    from freemad.evolve.variation import transcript_dir

    base = transcript_dir(cfg, run_id)
    try:
        base.mkdir(parents=True, exist_ok=True)
        path = base / f"intervention_it{iteration}.json"
        payload = {
            "final_solution": result.get("final_solution", ""),
            "transcript": result.get("transcript", []),
        }
        path.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
        return str(path)
    except OSError:
        return None
