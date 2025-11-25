from __future__ import annotations

import concurrent.futures
import logging
import time
from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List, Optional
import random
import uuid

from freemad.agents import AgentFactory
from freemad.config import Config
from freemad.scoring import ScoreTracker
from freemad.topology import build_topology
from freemad.utils import compute_answer_id
from freemad.utils.budget import BudgetGuard, BudgetExceeded, TokenBudget, enforce_size
from freemad.validation import ValidationManager
from freemad.validation.base import ValidationResult
from freemad.utils.logger import get_logger, log_event
from freemad.types import Decision, RoundType, TieBreak, LogEvent, RunEventKind
from freemad.run_events import RunEvent, RunObserver, NullObserver


class AnswerSelector:
    def __init__(self, tie_break: TieBreak, seed: int) -> None:
        self._tie_break = tie_break
        self._seed = seed

    def select(self, scores: Dict[str, float], conf: Dict[str, float], answers: Dict[str, str]) -> str:
        if not scores:
            if not answers:
                return ""
            return next(iter(answers.keys()))
        max_score = max(scores.values())
        top = [ans for ans, sc in scores.items() if sc == max_score]
        if len(top) == 1:
            return top[0]
        max_conf = max(conf.get(ans, 0.0) for ans in top)
        top2 = [ans for ans in top if conf.get(ans, 0.0) == max_conf]
        if len(top2) == 1:
            return top2[0]
        top2.sort()
        if self._tie_break == TieBreak.DETERMINISTIC:
            return top2[0]
        rnd = random.Random(self._seed)
        return rnd.choice(top2)


class DeadlineManager:
    def collect(
        self,
        futs: Dict[concurrent.futures.Future[Any], str],
        soft_s: float,
        hard_s: float,
        min_agents: int,
    ) -> tuple[Dict[str, Any], bool, bool, Dict[concurrent.futures.Future[Any], str]]:
        start = time.perf_counter()
        completed: Dict[str, Any] = {}
        remaining = dict(futs)
        deadline_hit_soft = False
        while True:
            now = time.perf_counter()
            remaining_soft = soft_s - (now - start)
            if remaining_soft <= 0:
                break
            done, _ = concurrent.futures.wait(
                list(remaining.keys()), timeout=remaining_soft, return_when=concurrent.futures.FIRST_COMPLETED
            )
            for d in done:
                aid = remaining.pop(d)
                try:
                    completed[aid] = d.result()
                except Exception as e:  # pragma: no cover - error handled by caller
                    completed[aid] = e
            if len(completed) >= min_agents:
                break
        if len(completed) < min_agents:
            deadline_hit_soft = True

        deadline_hit_hard = False
        while remaining:
            now = time.perf_counter()
            remaining_hard = hard_s - (now - start)
            if remaining_hard <= 0:
                deadline_hit_hard = True
                break
            done, _ = concurrent.futures.wait(
                list(remaining.keys()), timeout=remaining_hard, return_when=concurrent.futures.FIRST_COMPLETED
            )
            for d in done:
                aid = remaining.pop(d)
                try:
                    completed[aid] = d.result()
                except Exception as e:  # pragma: no cover - error handled by caller
                    completed[aid] = e
        return completed, deadline_hit_soft, deadline_hit_hard, remaining


@dataclass(frozen=True)
class TranscriptResponse:
    agent_id: str
    solution: str
    reasoning: str
    decision: Decision
    changed: bool
    answer_id: str
    metadata: dict


@dataclass(frozen=True)
class AgentRoundRecord:
    response: TranscriptResponse
    peers_assigned: List[str] = field(default_factory=list)
    peers_seen: List[str] = field(default_factory=list)


@dataclass(frozen=True)
class RoundTranscript:
    round_index: int
    type: RoundType  # generation | critique
    agents: Dict[str, AgentRoundRecord]
    scores: Dict[str, float]
    topology_info: dict
    deadline_hit_soft: bool = False
    deadline_hit_hard: bool = False


class Orchestrator:
    def __init__(self, cfg: Config, observer: Optional[RunObserver] = None):
        self.cfg = cfg
        self.factory = AgentFactory(cfg)
        self.agents = self.factory.build_all()
        self.topology = build_topology(cfg)
        self.score = ScoreTracker(cfg)
        self.answer_text: Dict[str, str] = {}
        self.logger = get_logger(cfg)
        self._token_budget = TokenBudget(cfg.budget.max_total_tokens, cfg.budget.enforce_total_tokens)
        self._observer: RunObserver = observer or NullObserver()
        self._selector = AnswerSelector(cfg.scoring.tie_break, cfg.scoring.random_seed)
        self._deadline_manager = DeadlineManager()

    def _emit(self, event: RunEvent) -> None:
        try:
            self._observer.on_event(event)
        except Exception as exc:
            # Observers must be best-effort and never break orchestration.
            log_event(self.logger, LogEvent.HEALTH_STATUS, level=logging.DEBUG, error=f"observer error: {exc}")
            return

    def _record_answer(self, text: str) -> str:
        ans_id = compute_answer_id(text)
        self.answer_text[ans_id] = text
        return ans_id

    def run(self, requirement: str, max_rounds: int = 1, run_id: Optional[str] = None) -> dict:
        run_id = run_id or str(uuid.uuid4())
        current_solution: Dict[str, str] = {}
        current_answer_id: Dict[str, str] = {}
        transcript: List[RoundTranscript] = []

        guard = BudgetGuard(self.cfg.budget.max_total_time_sec, self.cfg.budget.max_round_time_sec)
        guard.check_total()

        requirement_trunc, _ = enforce_size(
            requirement, self.cfg.security.max_requirement_size, label="requirement"
        )

        # Log the requirement we are about to send to all agents (truncated and redacted).
        log_event(
            self.logger,
            LogEvent.RUN_START,
            level=logging.INFO,
            run_id=run_id,
            requirement=requirement_trunc,
        )

        self._emit(
            RunEvent(
                kind=RunEventKind.RUN_STARTED,
                run_id=run_id,
                ts_ms=int(time.time() * 1000),
            )
        )

        # Round 0: generation
        self._run_generation_round(run_id, requirement_trunc, current_solution, current_answer_id, transcript, guard)
        # Critique rounds
        early_stop_reason, transcript = self._run_critique_rounds(
            run_id, requirement_trunc, max_rounds, guard, current_solution, current_answer_id, transcript
        )

        all_scores = self.score.get_all_scores()
        vm = ValidationManager(self.cfg)
        vresults, vconf = vm.validate_many(self.answer_text)
        log_event(self.logger, LogEvent.VALIDATION_DONE)
        best_ans = self._selector.select(all_scores, vconf, self.answer_text)
        final_solution = self.answer_text.get(best_ans, "")

        winning_agents = [aid for aid, ans in current_answer_id.items() if ans == best_ans]
        origin_agents: List[str] = []
        for t in transcript:
            holders = [aid for aid, rec in t.agents.items() if rec.response.answer_id == best_ans]
            if holders:
                origin_agents = holders
                break
        holders_history = {t.round_index: [aid for aid, rec in t.agents.items() if rec.response.answer_id == best_ans] for t in transcript}

        self._emit(
            RunEvent(
                kind=RunEventKind.FINAL_ANSWER_SELECTED,
                run_id=run_id,
                ts_ms=int(time.time() * 1000),
                final_answer_id=best_ans,
                winning_agents=winning_agents,
                scores=all_scores,
            )
        )

        result = {
            "final_answer_id": best_ans,
            "final_solution": final_solution,
            "scores": all_scores,
            "raw_scores": self.score.get_raw_scores(),
            "winning_agents": winning_agents,
            "origin_agents": origin_agents,
            "holders_history": holders_history,
            "early_stop_reason": early_stop_reason,
            "transcript": [
                {
                    "round": t.round_index,
                    "type": t.type.value,
                    "agents": {
                        aid: {
                            "response": (asdict(rec.response) | {"decision": rec.response.decision.value}),
                            "peers_assigned": rec.peers_assigned,
                            "peers_assigned_count": len(rec.peers_assigned),
                            "peers_seen": rec.peers_seen,
                            "peers_seen_count": len(rec.peers_seen),
                        }
                        for aid, rec in t.agents.items()
                    },
                    "scores": t.scores,
                    "topology_info": t.topology_info,
                    "deadline_hit_soft": t.deadline_hit_soft,
                    "deadline_hit_hard": t.deadline_hit_hard,
                }
                for t in transcript
            ],
            "validation": {ans: {name: vars(res) for name, res in vresults[ans].items()} for ans in self.answer_text.keys()},
            "validator_confidence": vconf,
            "score_explainers": {ans: [{**e.__dict__, "action": e.action.value} for e in self.score.explain_score(ans)] for ans in self.answer_text.keys()},
            "metrics": self._compute_metrics(transcript, best_ans, vresults),
        }
        self._emit(
            RunEvent(
                kind=RunEventKind.RUN_COMPLETED,
                run_id=run_id,
                ts_ms=int(time.time() * 1000),
                final_answer_id=best_ans,
            )
        )
        return result

    def _run_generation_round(
        self,
        run_id: str,
        requirement_trunc: str,
        current_solution: Dict[str, str],
        current_answer_id: Dict[str, str],
        transcript: List[RoundTranscript],
        guard: BudgetGuard,
    ) -> None:
        gen_agents: Dict[str, AgentRoundRecord] = {}
        log_event(self.logger, LogEvent.ROUND_START, round=0, type=RoundType.GENERATION.value)
        self._emit(
            RunEvent(
                kind=RunEventKind.ROUND_STARTED,
                run_id=run_id,
                ts_ms=int(time.time() * 1000),
                round_index=0,
                round_type=RoundType.GENERATION,
            )
        )
        max_workers = min(len(self.agents), self.cfg.budget.max_concurrent_agents or len(self.agents))
        with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as ex:
            gen_futs: Dict[concurrent.futures.Future[Any], str] = {}
            for aid, a in self.agents.items():
                self._emit(
                    RunEvent(
                        kind=RunEventKind.AGENT_GENERATE_STARTED,
                        run_id=run_id,
                        ts_ms=int(time.time() * 1000),
                        round_index=0,
                        round_type=RoundType.GENERATION,
                        agent_id=aid,
                    )
                )
                gen_futs[ex.submit(a.generate, requirement_trunc)] = aid
            for fut in concurrent.futures.as_completed(gen_futs):
                aid = gen_futs[fut]
                resp = fut.result()
                ans_id = self._record_answer(resp.solution)
                current_solution[aid] = resp.solution
                current_answer_id[aid] = ans_id
                if (resp.solution or "").strip():
                    self.score.record_initial(agent_id=aid, answer_id=ans_id, round_idx=0)
                t_in = int(resp.metadata.tokens.get("prompt", 0))
                t_out = int(resp.metadata.tokens.get("output", 0))
                self._token_budget.add(t_in + t_out)
                self._emit(
                    RunEvent(
                        kind=RunEventKind.AGENT_GENERATE_FINISHED,
                        run_id=run_id,
                        ts_ms=int(time.time() * 1000),
                        round_index=0,
                        round_type=RoundType.GENERATION,
                        agent_id=aid,
                        answer_id=ans_id,
                        decision=Decision.KEEP,
                        changed=False,
                    )
                )
                gen_agents[aid] = AgentRoundRecord(
                    response=TranscriptResponse(
                        agent_id=aid,
                        solution=resp.solution,
                        reasoning=resp.reasoning,
                        decision=Decision.KEEP,
                        changed=False,
                        answer_id=ans_id,
                        metadata=asdict(resp.metadata),
                    ),
                    peers_assigned=[],
                    peers_seen=[],
                )

        scores_round0 = self.score.get_all_scores()
        holders_round0: Dict[str, List[str]] = {
            ans: [aid for aid, curr in current_answer_id.items() if curr == ans] for ans in scores_round0.keys()
        }
        transcript.append(
            RoundTranscript(
                round_index=0,
                type=RoundType.GENERATION,
                agents=gen_agents,
                scores=scores_round0,
                topology_info=self.topology.info() if self.cfg.output.include_topology_info else {},
                deadline_hit_soft=False,
                deadline_hit_hard=False,
            )
        )
        log_event(self.logger, LogEvent.ROUND_END, round=0, type=RoundType.GENERATION.value)
        self._emit(
            RunEvent(
                kind=RunEventKind.SCORES_UPDATED,
                run_id=run_id,
                ts_ms=int(time.time() * 1000),
                round_index=0,
                round_type=RoundType.GENERATION,
                scores=scores_round0,
                holders=holders_round0,
            )
        )
        self._emit(
            RunEvent(
                kind=RunEventKind.ROUND_COMPLETED,
                run_id=run_id,
                ts_ms=int(time.time() * 1000),
                round_index=0,
                round_type=RoundType.GENERATION,
            )
        )

    def _run_critique_rounds(
        self,
        run_id: str,
        requirement_trunc: str,
        max_rounds: int,
        guard: BudgetGuard,
        current_solution: Dict[str, str],
        current_answer_id: Dict[str, str],
        transcript: List[RoundTranscript],
    ) -> tuple[Optional[str], List[RoundTranscript]]:
        early_stop_reason: Optional[str] = None
        for r in range(1, max_rounds + 1):
            try:
                guard.check_total()
            except BudgetExceeded:
                early_stop_reason = "total_time_budget_exceeded"
                log_event(self.logger, LogEvent.BUDGET_EXCEEDED, scope="total", round=r)
                break
            rs = guard.round_start()
            log_event(self.logger, LogEvent.ROUND_START, round=r, type=RoundType.CRITIQUE.value)
            self._emit(
                RunEvent(
                    kind=RunEventKind.ROUND_STARTED,
                    run_id=run_id,
                    ts_ms=int(time.time() * 1000),
                    round_index=r,
                    round_type=RoundType.CRITIQUE,
                )
            )
            peers_map = self.topology.assign_peers(list(self.agents.keys()))
            round_agents: Dict[str, AgentRoundRecord] = {}
            start = time.perf_counter()
            soft_s = self.cfg.deadlines.soft_timeout_ms / 1000.0
            hard_s = self.cfg.deadlines.hard_timeout_ms / 1000.0
            min_agents = self.cfg.deadlines.min_agents

            peer_bundles: Dict[str, List[str]] = {}
            for aid in self.agents.keys():
                assigned = peers_map.get(aid, [])
                peer_bundles[aid] = []
                for p in assigned:
                    if p in current_solution:
                        s, _ = enforce_size(current_solution[p], self.cfg.security.max_solution_size, label="peer_solution")
                        peer_bundles[aid].append(s)

            max_workers = min(len(self.agents), self.cfg.budget.max_concurrent_agents or len(self.agents))
            with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as ex:
                crit_futs: Dict[concurrent.futures.Future[Any], str] = {}
                for aid in self.agents.keys():
                    self._emit(
                        RunEvent(
                            kind=RunEventKind.AGENT_CRITIQUE_STARTED,
                            run_id=run_id,
                            ts_ms=int(time.time() * 1000),
                            round_index=r,
                            round_type=RoundType.CRITIQUE,
                            agent_id=aid,
                        )
                    )
                    fut = ex.submit(
                        self.agents[aid].critique_and_refine,
                        requirement_trunc,
                        enforce_size(current_solution.get(aid, ""), self.cfg.security.max_solution_size, label="own_solution")[0],
                        peer_bundles.get(aid, []),
                    )
                    crit_futs[fut] = aid
                completed_raw, deadline_hit_soft, deadline_hit_hard, _remaining = self._deadline_manager.collect(
                    crit_futs, soft_s=soft_s, hard_s=hard_s, min_agents=min_agents
                )
                if deadline_hit_soft:
                    log_event(self.logger, LogEvent.DEADLINE_SOFT, round=r, completed=len(completed_raw), min_agents=min_agents)
                if deadline_hit_hard:
                    log_event(self.logger, LogEvent.DEADLINE_HARD, round=r)

                completed: Dict[str, dict] = {}
                for aid, res in completed_raw.items():
                    if isinstance(res, Exception):
                        completed[aid] = {
                            "agent_id": aid,
                            "decision": Decision.KEEP,
                            "changed": False,
                            "solution": current_solution.get(aid, ""),
                            "reasoning": str(res),
                            "answer_id": current_answer_id.get(aid),
                        }
                    else:
                        try:
                            completed[aid] = asdict(res)
                        except Exception:
                            completed[aid] = {
                                "agent_id": aid,
                                "decision": Decision.KEEP,
                                "changed": False,
                                "solution": current_solution.get(aid, ""),
                                "reasoning": str(res),
                                "answer_id": current_answer_id.get(aid),
                            }

                for aid in self.agents.keys():
                    peers_assigned = peers_map.get(aid, [])
                    peers_seen = list(peers_assigned)
                    if aid not in completed:
                        self.score.record_keep(agent_id=aid, answer_id=current_answer_id[aid], round_idx=r)
                        round_agents[aid] = AgentRoundRecord(
                            response=TranscriptResponse(
                                agent_id=aid,
                                solution=current_solution[aid],
                                reasoning="timeout carry-forward",
                                decision=Decision.KEEP,
                                changed=False,
                                answer_id=current_answer_id[aid],
                                metadata={},
                            ),
                            peers_assigned=peers_assigned,
                            peers_seen=peers_seen,
                        )
                        self._emit(
                            RunEvent(
                                kind=RunEventKind.AGENT_CRITIQUE_FINISHED,
                                run_id=run_id,
                                ts_ms=int(time.time() * 1000),
                                round_index=r,
                                round_type=RoundType.CRITIQUE,
                                agent_id=aid,
                                answer_id=current_answer_id[aid],
                                decision=Decision.KEEP,
                                changed=False,
                            )
                        )
                        continue

                    res = completed[aid]
                    if res.get("decision") == Decision.REVISE and res.get("solution"):
                        old = current_answer_id[aid]
                        current_solution[aid] = res["solution"]
                        current_answer_id[aid] = res["answer_id"]
                        self._record_answer(res["solution"])
                        self.score.record_change(agent_id=aid, old_answer_id=old, new_answer_id=current_answer_id[aid], round_idx=r)
                    else:
                        self.score.record_keep(agent_id=aid, answer_id=current_answer_id[aid], round_idx=r)
                        res["decision"] = Decision.KEEP
                        res["changed"] = False
                        res["answer_id"] = current_answer_id[aid]

                    md_dict: Dict[str, Any] = {}
                    md = res.get("metadata", {}) or {}
                    md_dict = md if isinstance(md, dict) else {}
                    t_in = int(md_dict.get("tokens", {}).get("prompt", 0))
                    t_out = int(md_dict.get("tokens", {}).get("output", 0))
                    self._token_budget.add(t_in + t_out)

                    round_agents[aid] = AgentRoundRecord(
                        response=TranscriptResponse(
                            agent_id=res["agent_id"],
                            solution=res["solution"],
                            reasoning=res.get("reasoning", ""),
                            decision=res["decision"],
                            changed=res.get("changed", False),
                            answer_id=res["answer_id"],
                            metadata=md_dict,
                        ),
                        peers_assigned=peers_assigned,
                        peers_seen=peers_seen,
                    )
                    self._emit(
                        RunEvent(
                            kind=RunEventKind.AGENT_CRITIQUE_FINISHED,
                            run_id=run_id,
                            ts_ms=int(time.time() * 1000),
                            round_index=r,
                            round_type=RoundType.CRITIQUE,
                            agent_id=res["agent_id"],
                            answer_id=res["answer_id"],
                            decision=res["decision"],
                            changed=res.get("changed", False),
                        )
                    )

            scores_round = self.score.get_all_scores()
            holders_round: Dict[str, List[str]] = {
                ans: [aid for aid, curr in current_answer_id.items() if curr == ans] for ans in scores_round.keys()
            }
            transcript.append(
                RoundTranscript(
                    round_index=r,
                    type=RoundType.CRITIQUE,
                    agents=round_agents,
                    scores=scores_round,
                    topology_info=self.topology.info() if self.cfg.output.include_topology_info else {},
                    deadline_hit_soft=deadline_hit_soft,
                    deadline_hit_hard=deadline_hit_hard,
                )
            )
            log_event(self.logger, LogEvent.ROUND_END, round=r, type=RoundType.CRITIQUE.value)
            self._emit(
                RunEvent(
                    kind=RunEventKind.SCORES_UPDATED,
                    run_id=run_id,
                    ts_ms=int(time.time() * 1000),
                    round_index=r,
                    round_type=RoundType.CRITIQUE,
                    scores=scores_round,
                    holders=holders_round,
                )
            )
            self._emit(
                RunEvent(
                    kind=RunEventKind.ROUND_COMPLETED,
                    run_id=run_id,
                    ts_ms=int(time.time() * 1000),
                    round_index=r,
                    round_type=RoundType.CRITIQUE,
                )
            )

            try:
                guard.check_round(rs)
            except BudgetExceeded:
                early_stop_reason = "round_time_budget_exceeded"
                log_event(self.logger, LogEvent.BUDGET_EXCEEDED, scope="round", round=r)
                break
        return early_stop_reason, transcript

    def _compute_metrics(self, rounds: List[RoundTranscript], final_id: str, vresults: Dict[str, Dict[str, ValidationResult]]) -> Dict[str, float]:
        num_rounds = max(0, len(rounds) - 1)
        num_agents = len(self.agents)
        deadline_soft_hits = sum(1 for r in rounds if r.deadline_hit_soft)
        deadline_hard_hits = sum(1 for r in rounds if r.deadline_hit_hard)
        opinion_changes = 0
        for r in rounds:
            if r.type == RoundType.CRITIQUE:
                for rec in r.agents.values():
                    if rec.response.changed:
                        opinion_changes += 1
        final_agreement = 0.0
        if rounds:
            last = rounds[-1]
            final_agreement = sum(1 for rec in last.agents.values() if rec.response.answer_id == final_id) / float(num_agents or 1)
        scores = self.score.get_all_scores().values()
        if scores:
            smin, smax = min(scores), max(scores)
            smean = sum(scores) / len(list(scores))
        else:
            smin = smax = smean = 0.0
        v_final = vresults.get(final_id, {})
        v_pass = sum(1 for v in v_final.values() if getattr(v, 'passed', False))
        v_total = max(1, len(v_final))
        return {
            "num_rounds": float(num_rounds),
            "num_agents": float(num_agents),
            "deadline_soft_hits": float(deadline_soft_hits),
            "deadline_hard_hits": float(deadline_hard_hits),
            "opinion_changes": float(opinion_changes),
            "agreement_rate": float(final_agreement),
            "score_min": float(smin),
            "score_max": float(smax),
            "score_mean": float(smean),
            "validation_pass_rate": float(v_pass) / float(v_total),
        }
