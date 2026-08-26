from __future__ import annotations

import json
import time
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from freemad.agents.base import Agent
from freemad.agents.factory import AgentFactory
from freemad.config import Config, ConfigError, to_dict
from freemad.evolve.context import ContextInput, failure_signature, generate_context
from freemad.evolve.judge import (
    Judge,
    compare_scores_detail,
    compute_manifest_hash,
    target_met,
    within_regress_bounds,
)
from freemad.evolve.lineage import (
    Lineage,
    LineageError,
    NoChangesToCommit,
    ProtectedPathTampering,
)
from freemad.evolve.models import (
    EvolveRunSnapshot,
    IterationRecord,
    JudgeVerdict,
    ScoreVector,
    SupervisorDirective,
    VariationResult,
)
from freemad.evolve.store import EvolveStore
from freemad.prompts.evolve import build_escalation_question
from freemad.evolve.supervisor import (
    Supervisor,
    SupervisorFinding,
    active_directives_of,
)
from freemad.evolve.variation import (
    make_operator,
    require_act_capability,
    require_launchable,
    scope_worker_budget,
)
from freemad.utils.budget import enforce_size
from freemad.types import (
    CompareDirection,
    EvolveEventKind,
    EvolveRunStatus,
    EvolveStopReason,
    IterationOutcome,
    SupervisorCause,
    VariationKind,
)

NO_CHANGES_SIGNATURE = "no changes produced"


@dataclass
class _RunState:
    records: List[IterationRecord] = field(default_factory=list)
    directives: List[SupervisorDirective] = field(default_factory=list)
    interventions_since_best: int = 0
    last_intervention_iteration: int = -1


class EvolveOrchestrator:
    """M1 deterministic spine: baseline -> variation -> judge -> decide -> stop."""

    def __init__(self, cfg: Config, store_path: Optional[str | Path] = None):
        self._cfg = cfg
        # Everything the worker drives runs under the iteration budget; the judge does not.
        self._worker_cfg = scope_worker_budget(cfg)
        self._store_path = (
            Path(store_path) if store_path else Path(cfg.evolve.store_path)
        )
        self._store = EvolveStore(
            self._store_path, redact_patterns=cfg.security.redact_patterns
        )
        self._judge = Judge(cfg)
        self._factory = AgentFactory(self._worker_cfg)
        self._supervisor = Supervisor(cfg)
        self._state: Dict[str, _RunState] = {}
        self._manifest_stamps: Dict[str, str] = {}

    # ---------- lifecycle ----------

    def create_run(self, goal: str) -> EvolveRunSnapshot:
        if not goal or not goal.strip():
            raise ConfigError("evolve goal must be non-empty")
        if not self._cfg.evolve.judge.stages:
            raise ConfigError("evolve requires judge stages in config")
        if not self._cfg.evolve.judge.comparator:
            raise ConfigError("evolve requires a comparator in config")
        if self._cfg.evolve.variation.kind == VariationKind.SINGLE_AGENT:
            # evolve.md sections 3 and 8.9 put this at run creation. Discovering it at
            # iteration 1 raises a ConfigError that nothing maps to a status, leaving
            # the store advertising `running` forever.
            self._resolve_agent()

        run_id = self._store.new_run_id()
        lineage = Lineage(self._cfg, run_id)
        lineage.require_clean_repo()
        # Pin the seed to a sha now. A symbolic ref means different commits in different
        # places -- "HEAD" is the main repo's branch tip to `git ls-tree`, but the
        # detached run-branch tip inside a worktree -- and it moves under the run if
        # anyone commits on that branch. The measurement has to be anchored to one
        # immutable commit (evolve.md section 2.2).
        seed_ref = lineage.resolve_ref(self._cfg.evolve.seed_ref)
        lineage.init_run_branch(seed_ref)

        snapshot = EvolveRunSnapshot(
            run_id=run_id,
            goal=goal.strip(),
            manifest_hash=self.manifest_hash(goal.strip()),
            status=EvolveRunStatus.PENDING,
            seed_ref=seed_ref,
            run_branch=lineage.run_branch,
            repo_path=str(lineage.repo_root),
        )
        stored = self._store.create_run(snapshot)
        self._manifest_stamps[stored.run_id] = stored.manifest_hash
        self._emit(
            stored.run_id,
            0,
            EvolveEventKind.RUN_CREATED,
            {
                "goal": stored.goal,
                "manifest_hash": stored.manifest_hash,
                "fitness_hash": self.fitness_hash(),
                "seed_sha": seed_ref,
            },
        )
        return stored

    def run(self, run_id: str) -> EvolveRunSnapshot:
        snapshot = self._require_run(run_id)
        if snapshot.status in (EvolveRunStatus.PENDING, EvolveRunStatus.PAUSED):
            snapshot = self._mark_running(snapshot)
        while snapshot.status in (EvolveRunStatus.RUNNING,):
            snapshot = self.step(run_id)
        return snapshot

    def step(self, run_id: str) -> EvolveRunSnapshot:
        snapshot = self._require_run(run_id)
        if snapshot.status != EvolveRunStatus.RUNNING:
            return snapshot
        if snapshot.baseline_score is None:
            return self._run_baseline(snapshot)

        wall_deadline_ms = snapshot.created_at_ms + (
            self._cfg.evolve.stop.max_wall_clock_minutes * 60 * 1000
        )
        if time.time() * 1000 >= wall_deadline_ms:
            return self._stop(run_id, EvolveStopReason.WALL_CLOCK)

        if self.fitness_hash() != self._fitness_hash_at_creation(snapshot):
            return self._fatal_stop(
                run_id,
                snapshot,
                "fitness definition changed mid-run (judge and stop.target are immutable)",
            )
        try:
            return self._run_iteration(snapshot)
        except LineageError as exc:
            # evolve.md section 4.2: there is no state in which the run needs a human to
            # notice it is over. An escaping git failure used to leave status=running,
            # stop_reason=None and no RUN_STOPPED event, so an unattended run simply
            # stopped without ever saying so.
            return self._fatal_stop(run_id, snapshot, f"lineage failure: {exc}")

    def pause(self, run_id: str) -> EvolveRunSnapshot:
        snapshot = self._require_run(run_id)
        if snapshot.status == EvolveRunStatus.RUNNING:
            updated = replace(snapshot, status=EvolveRunStatus.PAUSED)
            self._store.update_run(updated)
            self._emit(run_id, updated.iteration, EvolveEventKind.RUN_PAUSED, {})
            return updated
        return snapshot

    def resume(self, run_id: str) -> EvolveRunSnapshot:
        snapshot = self._require_run(run_id)
        if snapshot.status == EvolveRunStatus.COMPLETED:
            return snapshot
        lineage = Lineage(self._cfg, run_id)
        removed = lineage.cleanup_orphan_worktrees()
        self._rebuild_records(run_id)
        snapshot = self._reconcile_with_branch(snapshot, lineage)
        updated = replace(snapshot, status=EvolveRunStatus.RUNNING, error=None)
        self._store.update_run(updated)
        self._emit(
            run_id, updated.iteration, EvolveEventKind.RUN_RESUMED, {"removed": removed}
        )
        return updated

    def stop(
        self, run_id: str, reason: EvolveStopReason = EvolveStopReason.MANUAL
    ) -> EvolveRunSnapshot:
        return self._stop(run_id, reason)

    def status(self, run_id: str) -> EvolveRunSnapshot:
        return self._require_run(run_id)

    # ---------- phases ----------

    def _run_baseline(self, snapshot: EvolveRunSnapshot) -> EvolveRunSnapshot:
        run_id = snapshot.run_id
        lineage = Lineage(self._cfg, run_id)
        try:
            worktree = lineage.baseline_worktree()
            hashes = lineage.restore_protected(worktree, snapshot.seed_ref)
            verdict = self._judge.judge_worktree(worktree)
        finally:
            lineage.remove_worktree(0)
        verdict = replace_hashes(verdict, hashes)

        self._emit(
            run_id,
            0,
            EvolveEventKind.BASELINE_JUDGED,
            {"verdict": verdict.to_dict()},
        )

        if verdict.failed_stage is not None:
            return self._fatal_stop(
                run_id,
                snapshot,
                f"baseline_gate_failed: seed judge stage '{verdict.failed_stage}' failed: "
                f"{enforce_size(verdict.failure_detail.strip(), 300, 'baseline_detail')[0]}",
            )
        if verdict.score is None or not verdict.gate_passed:
            return self._fatal_stop(
                run_id,
                snapshot,
                "baseline_gate_failed: seed does not pass its own gate",
            )

        # v0 marks the measured seed, so every later version has something to diff against.
        lineage.tag_version(0, lineage.resolve_ref(snapshot.seed_ref))

        updated = replace(
            snapshot,
            baseline_score=verdict.score,
            best_score=verdict.score,
            best_iteration=None,
            best_sha=None,
        )
        self._store.update_run(updated)

        if target_met(verdict.score, self._cfg.evolve.stop.target):
            return self._complete_target(run_id, updated)

        updated = self._merge_with_fresh(updated, iteration=1)
        self._store.update_run(updated)
        return updated

    def _run_iteration(self, snapshot: EvolveRunSnapshot) -> EvolveRunSnapshot:
        run_id = snapshot.run_id
        iteration = snapshot.iteration
        if iteration > self._cfg.evolve.stop.max_iterations:
            return self._stop(run_id, EvolveStopReason.MAX_ITERATIONS)

        self._emit(run_id, iteration, EvolveEventKind.ITERATION_STARTED, {})
        lineage = Lineage(self._cfg, run_id)
        operator = make_operator(self._worker_cfg)
        var = self._cfg.evolve.variation
        worker_agent: Optional[Agent] = (
            self._resolve_agent() if var.kind == VariationKind.SINGLE_AGENT else None
        )

        context_doc = self._context_for(run_id, snapshot)
        tip_before = lineage.resolve_ref(lineage.run_branch)
        worktree = lineage.create_worktree(iteration)
        try:
            outcome = operator.propose(
                context_doc=context_doc,
                worktree=worktree,
                directives=tuple(
                    d.text
                    for d in active_directives_of(
                        self._state_for(run_id).directives, snapshot.iteration
                    )
                ),
                agent=worker_agent,
                run_id=run_id,
                iteration=iteration,
                goal=snapshot.goal,
            )

            variation = VariationResult(
                kind=var.kind,
                agent_ids=(
                    (worker_agent.agent_cfg.id,)
                    if worker_agent is not None
                    else outcome.agent_ids
                ),
                produced_changes=outcome.result_changed_files,
                diff_stat=lineage.diff_stat(worktree),
                self_report=outcome.self_report,
                final_output=outcome.final_output,
                worker_error=outcome.worker_error,
                transcript_ref=outcome.transcript_ref,
                duration_ms=outcome.duration_ms,
            )
            self._emit(
                run_id,
                iteration,
                EvolveEventKind.VARIATION_PRODUCED,
                variation.to_dict(),
            )

            if not variation.produced_changes:
                # Release the worktree before `_reject`: it runs the supervisor, whose
                # intervention is a whole debate, and the `finally` would otherwise hold
                # the checkout for minutes. `remove_worktree` is idempotent.
                lineage.remove_worktree(iteration)
                return self._reject(
                    run_id,
                    snapshot,
                    iteration,
                    variation,
                    IterationOutcome.WORKER_FAILED,
                    signature=NO_CHANGES_SIGNATURE,
                    score=None,
                    detail=(variation.worker_error or NO_CHANGES_SIGNATURE),
                )

            try:
                hashes = lineage.restore_protected(worktree, snapshot.seed_ref)
            except ProtectedPathTampering as exc:
                lineage.remove_worktree(iteration)
                return self._reject(
                    run_id,
                    snapshot,
                    iteration,
                    variation,
                    IterationOutcome.WORKER_FAILED,
                    signature="protected path tampering",
                    score=None,
                    detail=enforce_size(str(exc), 1000, "rejection_detail")[0],
                )
            verdict = self._judge.judge_worktree(worktree)
            try:
                lineage.verify_protected(worktree, snapshot.seed_ref)
            except ProtectedPathTampering as exc:
                lineage.remove_worktree(iteration)
                return self._reject(
                    run_id,
                    snapshot,
                    iteration,
                    variation,
                    IterationOutcome.WORKER_FAILED,
                    signature="protected path tampering",
                    score=None,
                    detail=enforce_size(str(exc), 1000, "rejection_detail")[0],
                )
            verdict = replace_hashes(verdict, hashes)
            self._emit(
                run_id,
                iteration,
                EvolveEventKind.CANDIDATE_JUDGED,
                {
                    "verdict": verdict.to_dict(),
                    "duration_ms": outcome.duration_ms,
                },
            )

            assert verdict.score is not None
            incumbent = (
                snapshot.best_score
                if snapshot.best_score is not None
                else (snapshot.baseline_score or ScoreVector())
            )
            best_ever = self._best_envelope(run_id, snapshot)

            # A failed stage short-circuits the pipeline, so the components it would
            # have provided are absent from the score. If none of them happen to be
            # gated, the gate passes on a partial vector and a candidate that broke
            # the test suite gets admitted. Fail closed on the stage itself.
            if verdict.failed_stage is not None:
                lineage.remove_worktree(iteration)
                return self._reject_verdict(
                    run_id,
                    snapshot,
                    iteration,
                    variation,
                    verdict,
                    IterationOutcome.REJECTED_GATE,
                )

            if not verdict.gate_passed:
                lineage.remove_worktree(iteration)
                return self._reject_verdict(
                    run_id,
                    snapshot,
                    iteration,
                    variation,
                    verdict,
                    IterationOutcome.REJECTED_GATE,
                )

            ok_regress, regress_detail = within_regress_bounds(
                verdict.score, best_ever, self._cfg.evolve.judge.comparator
            )
            if not ok_regress:
                lineage.remove_worktree(iteration)
                return self._reject(
                    run_id,
                    snapshot,
                    iteration,
                    variation,
                    IterationOutcome.REJECTED_NOT_BETTER,
                    signature="regression bound violated",
                    score=verdict.score,
                    detail=regress_detail or "regression bound violated",
                )
            is_better, compare_detail = compare_scores_detail(
                verdict.score, incumbent, self._cfg.evolve.judge.comparator
            )
            if not is_better:
                lineage.remove_worktree(iteration)
                return self._reject(
                    run_id,
                    snapshot,
                    iteration,
                    variation,
                    IterationOutcome.REJECTED_NOT_BETTER,
                    signature=compare_detail or "not better than incumbent",
                    score=verdict.score,
                    detail=compare_detail or "not better than incumbent",
                )

            try:
                sha = lineage.commit_candidate(
                    worktree,
                    iteration,
                    json.dumps(verdict.score.to_dict(), sort_keys=True),
                )
            except NoChangesToCommit as exc:
                # Judged better, but the improvement was measurement noise or lived
                # entirely in a protected path that restoration undid.
                lineage.remove_worktree(iteration)
                return self._reject(
                    run_id,
                    snapshot,
                    iteration,
                    variation,
                    IterationOutcome.WORKER_FAILED,
                    signature=NO_CHANGES_SIGNATURE,
                    score=verdict.score,
                    detail=enforce_size(str(exc), 1000, "rejection_detail")[0],
                )
            tag = lineage.tag_version(iteration, sha)
            lineage.advance_run_branch(sha, tip_before)

            self._emit(
                run_id,
                iteration,
                EvolveEventKind.CANDIDATE_COMMITTED,
                {
                    "sha": sha,
                    "tag": tag,
                    "score": verdict.score.to_dict(),
                    "diff_stat": variation.diff_stat,
                },
            )
            self._remember(
                run_id,
                IterationRecord(
                    iteration=iteration,
                    kind=variation.kind,
                    outcome=IterationOutcome.COMMITTED,
                    score=verdict.score,
                    sha=sha,
                    tag=tag,
                    self_report=variation.self_report,
                    started_at_ms=snapshot.updated_at_ms,
                    duration_ms=outcome.duration_ms,
                ),
            )

            updated = self._merge_with_fresh(
                snapshot,
                iteration=iteration + 1,
                best_iteration=iteration,
                best_sha=sha,
                best_score=verdict.score,
                interventions_without_new_best=0,
            )
            self._store.update_run(updated)

            state = self._state_for(run_id)
            state.interventions_since_best = 0

            if target_met(verdict.score, self._cfg.evolve.stop.target):
                return self._complete_target(run_id, updated)
            return updated
        finally:
            lineage.remove_worktree(iteration)

    # ---------- rejection / stops ----------

    def _reject_verdict(
        self,
        run_id: str,
        snapshot: EvolveRunSnapshot,
        iteration: int,
        variation: VariationResult,
        verdict: JudgeVerdict,
        outcome: IterationOutcome,
    ) -> EvolveRunSnapshot:
        sig = failure_signature(verdict)
        detail = (
            "; ".join(f.describe() for f in verdict.gate_failures)
            or verdict.failure_detail
        )
        return self._reject(
            run_id,
            snapshot,
            iteration,
            variation,
            outcome,
            signature=sig,
            score=verdict.score,
            detail=enforce_size(detail, 1000, "rejection_detail")[0],
        )

    def _reject(
        self,
        run_id: str,
        snapshot: EvolveRunSnapshot,
        iteration: int,
        variation: VariationResult,
        outcome: IterationOutcome,
        signature: str,
        score: Optional[ScoreVector],
        detail: str,
    ) -> EvolveRunSnapshot:
        self._emit(
            run_id,
            iteration,
            EvolveEventKind.CANDIDATE_REJECTED,
            {
                "outcome": outcome.value,
                "failure_signature": signature,
                "detail": detail,
                "score": (score.to_dict() if score is not None else None),
            },
        )
        self._remember(
            run_id,
            IterationRecord(
                iteration=iteration,
                kind=variation.kind,
                outcome=outcome,
                score=score,
                failure_signature=signature,
                self_report=variation.self_report,
                started_at_ms=snapshot.updated_at_ms,
                duration_ms=variation.duration_ms,
            ),
        )
        updated = self._merge_with_fresh(snapshot, iteration=iteration + 1)
        self._store.update_run(updated)
        return self._supervisor_check(updated)

    # ---------- supervisor / escalation ----------

    def _supervisor_check(self, snapshot: EvolveRunSnapshot) -> EvolveRunSnapshot:
        run_id = snapshot.run_id
        state = self._state_for(run_id)
        finding = self._supervisor.detect(
            records=tuple(state.records),
            current_iteration=snapshot.iteration,
            last_intervention_iteration=state.last_intervention_iteration,
            cooldown_iterations=self._cfg.evolve.supervisor.directions_ttl_iterations,
        )
        if finding is None:
            return snapshot

        max_before_human = self._cfg.evolve.supervisor.max_interventions_before_human
        if state.interventions_since_best >= max_before_human:
            return self._escalate(snapshot, finding)

        self._emit(
            run_id,
            snapshot.iteration,
            EvolveEventKind.SUPERVISOR_TRIGGERED,
            {"cause": finding.cause.value, "detail": finding.detail},
        )
        state.last_intervention_iteration = snapshot.iteration
        state.interventions_since_best += 1
        snapshot = self._persist_intervention_count(
            snapshot, state.interventions_since_best
        )
        active = [
            d.text for d in active_directives_of(state.directives, snapshot.iteration)
        ]
        result = self._supervisor.intervene(
            snapshot_goal=snapshot.goal,
            records=tuple(state.records),
            best_score=snapshot.best_score,
            baseline_score=snapshot.baseline_score,
            best_sha=snapshot.best_sha,
            finding=finding,
            active_directives=active,
            debate_run_id=run_id,
            iteration=snapshot.iteration,
        )
        if result.error or not result.directives:
            self._emit(
                run_id,
                snapshot.iteration,
                EvolveEventKind.SUPERVISOR_DIRECTIONS,
                {"error": result.error or "no directions", "directions": []},
            )
            return snapshot

        state.directives.extend(result.directives)
        self._emit(
            run_id,
            snapshot.iteration,
            EvolveEventKind.SUPERVISOR_DIRECTIONS,
            {
                "directions": [d.text for d in result.directives],
                "transcript_ref": result.transcript_ref,
                "cause": finding.cause.value,
                "ttl": self._cfg.evolve.supervisor.directions_ttl_iterations,
            },
        )
        return snapshot

    def _escalate(
        self, snapshot: EvolveRunSnapshot, finding: SupervisorFinding
    ) -> EvolveRunSnapshot:
        run_id = snapshot.run_id
        state = self._state_for(run_id)
        accepted = [r for r in state.records if r.outcome == IterationOutcome.COMMITTED]
        recent_failures = [
            f"it{r.iteration}: {r.failure_signature or 'unknown'}"
            for r in state.records[-6:]
            if r.outcome != IterationOutcome.COMMITTED
        ]
        question = build_escalation_question(
            goal=snapshot.goal,
            best_iteration=snapshot.best_iteration,
            best_sha=snapshot.best_sha,
            best_score=(snapshot.best_score.to_dict() if snapshot.best_score else {}),
            accepted=[
                (r.self_report.splitlines()[0][:80] if r.self_report else "(no report)")
                for r in accepted
            ][-5:],
            interventions=state.interventions_since_best,
            recent_failures=recent_failures,
        )
        fresh = self._store.get_run(run_id)
        if fresh is not None and fresh.status in (
            EvolveRunStatus.STOPPED,
            EvolveRunStatus.FAILED,
            EvolveRunStatus.COMPLETED,
        ):
            # Someone stopped the run while the intervention was running; do not
            # resurrect it into WAITING_FOR_HUMAN.
            return fresh
        waiting = replace(
            snapshot,
            status=EvolveRunStatus.WAITING_FOR_HUMAN,
            error=finding.detail,
        )
        self._store.update_run(waiting)
        self._emit(
            run_id,
            snapshot.iteration,
            EvolveEventKind.HUMAN_ESCALATED,
            {"question": question, "cause": finding.cause.value},
        )
        return waiting

    def answer(self, run_id: str, text: str) -> EvolveRunSnapshot:
        """Inject human guidance as a directive and resume the run."""
        snapshot = self._require_run(run_id)
        self._require_waiting_for_human(snapshot, "answer")
        stripped = (text or "").strip()
        if not stripped:
            raise ConfigError("human answer text must be non-empty")
        self._store.append_event(
            run_id,
            EvolveEventKind.HUMAN_INPUT_RECEIVED,
            snapshot.iteration,
            {"directive": enforce_size(stripped, 2000, "human_directive")[0]},
        )
        state = self._state_for(run_id)
        # Fresh guidance restores the supervisor's autonomous attempts; without this
        # the next finding re-escalates to the human immediately.
        state.interventions_since_best = 0
        snapshot = self._persist_intervention_count(snapshot, 0)
        state.directives.append(
            SupervisorDirective(
                directive_id=f"{run_id}-h{len(state.directives)}-{snapshot.iteration}",
                text=enforce_size(stripped, 2000, "human_directive")[0],
                source_ref="human",
                cause=SupervisorCause.STALL,
                created_iteration=snapshot.iteration,
                ttl_iterations=self._cfg.evolve.supervisor.directions_ttl_iterations,
            )
        )
        updated = replace(snapshot, status=EvolveRunStatus.RUNNING, error=None)
        self._store.update_run(updated)
        self._emit(
            run_id, updated.iteration, EvolveEventKind.RUN_RESUMED, {"via": "answer"}
        )
        return updated

    def decline(self, run_id: str) -> EvolveRunSnapshot:
        """Human declined to guide: a valid clean stop."""
        self._require_waiting_for_human(self._require_run(run_id), "decline")
        return self._stop(run_id, EvolveStopReason.HUMAN_DECLINED)

    @staticmethod
    def _require_waiting_for_human(snapshot: EvolveRunSnapshot, verb: str) -> None:
        """Both verbs answer an escalation; neither may overwrite a finished run.

        Unguarded, `decline` turned a `completed`/`target_reached` run into
        `stopped`/`human_declined`, and `answer` resurrected it and kept iterating.
        """
        if snapshot.status != EvolveRunStatus.WAITING_FOR_HUMAN:
            raise ConfigError(
                f"cannot {verb}: run {snapshot.run_id} is not waiting for human input "
                f"(status: {snapshot.status.value})"
            )

    def _complete_target(
        self, run_id: str, snapshot: EvolveRunSnapshot
    ) -> EvolveRunSnapshot:
        completed = replace(
            snapshot,
            status=EvolveRunStatus.COMPLETED,
            stop_reason=EvolveStopReason.TARGET_REACHED.value,
        )
        self._store.update_run(completed)
        self._emit(
            run_id,
            snapshot.iteration,
            EvolveEventKind.RUN_STOPPED,
            {
                "reason": EvolveStopReason.TARGET_REACHED.value,
                "status": EvolveRunStatus.COMPLETED.value,
                "error": None,
            },
        )
        return completed

    def _stop(self, run_id: str, reason: EvolveStopReason) -> EvolveRunSnapshot:
        snapshot = self._require_run(run_id)
        status = (
            EvolveRunStatus.FAILED
            if reason == EvolveStopReason.FATAL_ERROR
            else EvolveRunStatus.STOPPED
        )
        stopped = replace(
            snapshot,
            status=status,
            stop_reason=reason.value,
        )
        self._store.update_run(stopped)
        self._emit(
            run_id,
            snapshot.iteration,
            EvolveEventKind.RUN_STOPPED,
            {"reason": reason.value, "status": status.value, "error": stopped.error},
        )
        return stopped

    def _fatal_stop(
        self, run_id: str, snapshot: EvolveRunSnapshot, error: str
    ) -> EvolveRunSnapshot:
        failed = replace(
            snapshot,
            status=EvolveRunStatus.FAILED,
            stop_reason=EvolveStopReason.FATAL_ERROR.value,
            error=error,
        )
        self._store.update_run(failed)
        self._emit(
            run_id,
            snapshot.iteration,
            EvolveEventKind.RUN_STOPPED,
            {
                "reason": EvolveStopReason.FATAL_ERROR.value,
                "status": EvolveRunStatus.FAILED.value,
                "error": error,
            },
        )
        return failed

    # ---------- helpers ----------

    def _context_for(self, run_id: str, snapshot: EvolveRunSnapshot) -> str:
        state = self._state_for(run_id)
        directives = [
            d.text for d in active_directives_of(state.directives, snapshot.iteration)
        ]
        return generate_context(
            ContextInput(
                goal=snapshot.goal,
                iteration=snapshot.iteration,
                best_iteration=snapshot.best_iteration,
                best_sha=snapshot.best_sha,
                best_score=snapshot.best_score,
                baseline_score=snapshot.baseline_score,
                records=tuple(state.records),
                directives=tuple(directives),
            ),
            budget_chars=self._cfg.evolve.context_budget_chars,
        )

    def _resolve_agent(self) -> Agent:
        var = self._cfg.evolve.variation
        if not (var.agent_id and var.agent_id.strip()):
            raise ConfigError(
                "evolve.variation.agent_id is required for single_agent variation"
            )
        agents = self._factory.build_all()
        agent = agents.get(var.agent_id)
        if agent is None:
            raise ConfigError(
                f"evolve variation agent '{var.agent_id}' is not an enabled agent"
            )
        require_act_capability(agent)
        require_launchable(agent)
        return agent

    def _merge_with_fresh(
        self, snapshot: EvolveRunSnapshot, **fields: object
    ) -> EvolveRunSnapshot:
        """Advance fields without clobbering an externally requested status (pause/stop)."""
        fresh = self._store.get_run(snapshot.run_id)
        if (
            fresh is not None
            and fresh.status != snapshot.status
            and fields.get("status") is None
            and fresh.status
            in (EvolveRunStatus.PAUSED, EvolveRunStatus.STOPPED, EvolveRunStatus.FAILED)
        ):
            fields["status"] = fresh.status
        return replace(snapshot, **fields)  # type: ignore[arg-type]

    def _reconcile_with_branch(
        self, snapshot: EvolveRunSnapshot, lineage: Lineage
    ) -> EvolveRunSnapshot:
        """Adopt an iteration that committed but never reached the snapshot.

        `commit -> tag -> advance branch -> emit -> update_run` is not atomic. A crash
        after the branch advanced leaves the lineage ahead of the store, and re-running
        that iteration commits a *second* time under the same number: two COMMITTED
        records for iteration N, a moved tag, and a report that renders it twice.
        """
        try:
            tip = lineage.resolve_ref(lineage.run_branch)
        except LineageError:
            return snapshot
        if tip == snapshot.best_sha:
            return snapshot
        for event in reversed(self._store.list_events(snapshot.run_id)):
            if event.kind != EvolveEventKind.CANDIDATE_COMMITTED:
                continue
            if str(event.payload.get("sha")) != tip:
                break
            recovered = replace(
                snapshot,
                iteration=max(snapshot.iteration, event.iteration + 1),
                best_iteration=event.iteration,
                best_sha=tip,
                best_score=ScoreVector.from_dict(event.payload["score"]),
                interventions_without_new_best=0,
            )
            self._store.update_run(recovered)
            return recovered
        return snapshot

    def _best_envelope(self, run_id: str, snapshot: EvolveRunSnapshot) -> ScoreVector:
        """The best value each component has ever reached — what `max_regress` guards.

        Neither obvious candidate is right on its own. Against the *baseline* the floor
        never moves, so a component can be dropped off a hard-won peak in one step.
        Against the *incumbent* the floor moves every acceptance, so drops compound —
        exactly the ratchet `evolve.md` section 8.3 says this bound exists to close.
        The per-component envelope stops both.
        """
        records = self._state_for(run_id).records
        history = [snapshot.baseline_score] + [
            r.score for r in records if r.outcome == IterationOutcome.COMMITTED
        ]
        seen = [s for s in history if s is not None]
        envelope: Dict[str, float] = {}
        for term in self._cfg.evolve.judge.comparator:
            values = [v for v in (s.get(term.component) for s in seen) if v is not None]
            if not values:
                continue
            envelope[term.component] = (
                max(values)
                if term.direction == CompareDirection.MAXIMIZE
                else min(values)
            )
        return ScoreVector(components=envelope)

    def _persist_intervention_count(
        self, snapshot: EvolveRunSnapshot, count: int
    ) -> EvolveRunSnapshot:
        """Mirror the in-memory counter into the snapshot so `status` can show it."""
        updated = self._merge_with_fresh(snapshot, interventions_without_new_best=count)
        self._store.update_run(updated)
        return updated

    def _remember(self, run_id: str, record: IterationRecord) -> None:
        self._state_for(run_id).records.append(record)

    def _state_for(self, run_id: str) -> _RunState:
        if run_id not in self._state:
            self._rebuild_records(run_id)
        return self._state[run_id]

    def _rebuild_records(self, run_id: str) -> List[IterationRecord]:
        events = self._store.list_events(run_id)
        records: List[IterationRecord] = []
        pending_kind: Dict[int, VariationResult] = {}
        judged: Dict[int, Tuple[Optional[ScoreVector], int]] = {}
        for event in events:
            try:
                payload = dict(event.payload)
                if event.kind == EvolveEventKind.VARIATION_PRODUCED:
                    pending_kind[event.iteration] = VariationResult.from_dict(payload)
                elif event.kind == EvolveEventKind.CANDIDATE_JUDGED:
                    verdict_raw = payload.get("verdict") or {}
                    score_raw = verdict_raw.get("score")
                    judged[event.iteration] = (
                        (ScoreVector.from_dict(score_raw) if score_raw else None),
                        int(payload.get("duration_ms", 0)),
                    )
                elif event.kind in (
                    EvolveEventKind.CANDIDATE_COMMITTED,
                    EvolveEventKind.CANDIDATE_REJECTED,
                ):
                    variation = pending_kind.get(event.iteration)
                    kind = variation.kind if variation else VariationKind.SINGLE_AGENT
                    self_report = variation.self_report if variation else ""
                    duration = variation.duration_ms if variation else 0
                    score, j_duration = judged.get(event.iteration, (None, 0))
                    if event.kind == EvolveEventKind.CANDIDATE_COMMITTED:
                        score = ScoreVector.from_dict(payload["score"])
                        records.append(
                            IterationRecord(
                                iteration=event.iteration,
                                kind=kind,
                                outcome=IterationOutcome.COMMITTED,
                                score=score,
                                sha=str(payload["sha"]),
                                tag=str(payload["tag"]),
                                self_report=self_report,
                                started_at_ms=event.ts_ms,
                                duration_ms=duration or j_duration,
                            )
                        )
                    else:
                        outcome = IterationOutcome(str(payload["outcome"]))
                        records.append(
                            IterationRecord(
                                iteration=event.iteration,
                                kind=kind,
                                outcome=outcome,
                                score=score,
                                failure_signature=(
                                    str(payload["failure_signature"])
                                    if payload.get("failure_signature")
                                    else None
                                ),
                                self_report=self_report,
                                started_at_ms=event.ts_ms,
                                duration_ms=duration or j_duration,
                            )
                        )
            except (KeyError, ValueError, TypeError):
                continue
        state = _RunState(records=sorted(records, key=lambda r: r.iteration))
        for event in events:
            try:
                payload = dict(event.payload)
                if event.kind == EvolveEventKind.CANDIDATE_COMMITTED:
                    # Mirrors the live path: a new best clears the escalation budget.
                    state.interventions_since_best = 0
                elif event.kind == EvolveEventKind.SUPERVISOR_TRIGGERED:
                    state.interventions_since_best += 1
                    state.last_intervention_iteration = event.iteration
                elif event.kind == EvolveEventKind.SUPERVISOR_DIRECTIONS:
                    ttl = int(payload.get("ttl", 0)) or (
                        self._cfg.evolve.supervisor.directions_ttl_iterations
                    )
                    for i, text in enumerate(payload.get("directions", [])):
                        state.directives.append(
                            SupervisorDirective(
                                directive_id=f"{event.run_id}-d{event.iteration}-{i}",
                                text=str(text),
                                source_ref=str(
                                    payload.get("transcript_ref") or event.run_id
                                ),
                                cause=self._cause_from_event(payload),
                                created_iteration=event.iteration,
                                ttl_iterations=ttl,
                            )
                        )
                elif event.kind == EvolveEventKind.HUMAN_INPUT_RECEIVED:
                    state.interventions_since_best = 0
                    text = str(payload.get("directive", "")).strip()
                    if text:
                        state.directives.append(
                            SupervisorDirective(
                                directive_id=f"{event.run_id}-h{event.ts_ms}",
                                text=text,
                                source_ref="human",
                                cause=SupervisorCause.STALL,
                                created_iteration=event.iteration,
                                ttl_iterations=(
                                    self._cfg.evolve.supervisor.directions_ttl_iterations
                                ),
                            )
                        )
            except (KeyError, ValueError, TypeError):
                continue
        self._state[run_id] = state
        return state.records

    @staticmethod
    def _cause_from_event(payload: dict) -> SupervisorCause:
        try:
            return SupervisorCause(
                str(payload.get("cause", SupervisorCause.STALL.value))
            )
        except ValueError:
            return SupervisorCause.STALL

    def _require_run(self, run_id: str) -> EvolveRunSnapshot:
        snapshot = self._store.get_run(run_id)
        if snapshot is None:
            raise ConfigError(f"unknown evolve run id: {run_id}")
        return snapshot

    def _mark_running(self, snapshot: EvolveRunSnapshot) -> EvolveRunSnapshot:
        updated = replace(snapshot, status=EvolveRunStatus.RUNNING)
        self._store.update_run(updated)
        self._emit(snapshot.run_id, snapshot.iteration, EvolveEventKind.RUN_STARTED, {})
        return updated

    def _emit(
        self, run_id: str, iteration: int, kind: EvolveEventKind, payload: dict
    ) -> None:
        # "stamp into every event" (section 2.2): without it the audit trail cannot say
        # which configuration produced any given record.
        stamped = {**payload, "manifest_hash": self._manifest_stamp(run_id)}
        self._store.append_event(run_id, kind, iteration, stamped)

    def _manifest_stamp(self, run_id: str) -> str:
        cached = self._manifest_stamps.get(run_id)
        if cached is None:
            snapshot = self._store.get_run(run_id)
            cached = snapshot.manifest_hash if snapshot else ""
            self._manifest_stamps[run_id] = cached
        return cached

    def manifest_hash(self, goal: str) -> str:
        """Goal plus the whole evolve config: what this run *is*.

        Section 2.2 asks for two different things and they are not the same value. This
        is the one stamped into the run, so resuming against a config that redefines the
        goal, the stop conditions, the variation operator or the worker agent is caught
        -- judge-only hashing let `stop.target` be weakened mid-run in silence.
        """
        return compute_manifest_hash(goal, to_dict(self._cfg)["evolve"])

    def fitness_hash(self) -> str:
        """What "better" and "done" mean: the judge, plus `stop.target`.

        Section 2.2 re-verifies the judge subsection every iteration. `stop.target` rides
        with it because it is evaluated over the same components and decides when the run
        declares success -- hashing the judge alone let a resume quietly lower the bar.
        Everything else in the section (iteration caps, budgets, supervisor knobs) stays
        out, so resuming with a longer budget is still allowed.
        """
        evolve = to_dict(self._cfg)["evolve"]
        return compute_manifest_hash(
            "", {"judge": evolve["judge"], "target": evolve["stop"]["target"]}
        )

    def _fitness_hash_at_creation(self, snapshot: EvolveRunSnapshot) -> str:
        for event in self._store.list_events(snapshot.run_id):
            if event.kind == EvolveEventKind.RUN_CREATED:
                recorded = event.payload.get("fitness_hash")
                if recorded:
                    return str(recorded)
        return self.fitness_hash()

    def close(self) -> None:
        self._store.close()


def replace_hashes(verdict: JudgeVerdict, hashes: Dict[str, str]) -> JudgeVerdict:
    return replace(verdict, protected_hashes=dict(hashes))
