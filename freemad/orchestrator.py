from __future__ import annotations

import concurrent.futures
import time
from dataclasses import dataclass, field, asdict
from typing import Dict, List, Optional

from freemad.agents import AgentFactory
from freemad.config import Config
from freemad.scoring import ScoreTracker
from freemad.topology import build_topology
from freemad.utils import compute_answer_id
from freemad.utils.budget import BudgetGuard, BudgetExceeded, TokenBudget, enforce_size
from freemad.validation import ValidationManager
from freemad.utils.logger import get_logger, log_event
from freemad.types import Decision, RoundType, TieBreak, LogEvent
import random


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
    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.factory = AgentFactory(cfg)
        self.agents = self.factory.build_all()
        self.topology = build_topology(cfg)
        self.score = ScoreTracker(cfg)
        self.answer_text: Dict[str, str] = {}
        self.logger = get_logger(cfg)
        self._token_budget = TokenBudget(cfg.budget.max_total_tokens, cfg.budget.enforce_total_tokens)

    def _record_answer(self, text: str) -> str:
        ans_id = compute_answer_id(text)
        self.answer_text[ans_id] = text
        return ans_id

    def run(self, requirement: str, max_rounds: int = 1) -> dict:
        current_solution: Dict[str, str] = {}
        current_answer_id: Dict[str, str] = {}
        transcript: List[RoundTranscript] = []

        guard = BudgetGuard(self.cfg.budget.max_total_time_sec, self.cfg.budget.max_round_time_sec)
        guard.check_total()

        requirement_trunc, _ = enforce_size(requirement, self.cfg.security.max_requirement_size, label="requirement")

        # Round 0: generation
        gen_agents: Dict[str, AgentRoundRecord] = {}
        log_event(self.logger, LogEvent.ROUND_START, round=0, type=RoundType.GENERATION.value)
        max_workers = min(len(self.agents), self.cfg.budget.max_concurrent_agents or len(self.agents))
        with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as ex:
            futs = {ex.submit(a.generate, requirement_trunc): (aid, a) for aid, a in self.agents.items()}
            for fut in concurrent.futures.as_completed(futs):
                aid, _a = futs[fut]
                resp = fut.result()
                ans_id = self._record_answer(resp.solution)
                current_solution[aid] = resp.solution
                current_answer_id[aid] = ans_id
                if (resp.solution or "").strip():
                    self.score.record_initial(agent_id=aid, answer_id=ans_id, round_idx=0)
                try:
                    t_in = int(resp.metadata.tokens.get("prompt", 0))
                    t_out = int(resp.metadata.tokens.get("output", 0))
                    self._token_budget.add(t_in + t_out)
                except Exception:
                    pass
                gen_agents[aid] = AgentRoundRecord(
                    response=TranscriptResponse(
                        agent_id=aid,
                        solution=resp.solution,
                        reasoning=resp.reasoning,
                        decision=Decision.KEEP,
                        changed=False,
                        answer_id=ans_id,
                        metadata=resp.metadata.__dict__,
                    ),
                    peers_assigned=[],
                    peers_seen=[],
                )

        transcript.append(
            RoundTranscript(
                round_index=0,
                type=RoundType.GENERATION,
                agents=gen_agents,
                scores=self.score.get_all_scores(),
                topology_info=self.topology.info() if self.cfg.output.include_topology_info else {},
                deadline_hit_soft=False,
                deadline_hit_hard=False,
            )
        )
        log_event(self.logger, LogEvent.ROUND_END, round=0, type=RoundType.GENERATION.value)

        # Critique rounds
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
                futs = {
                    ex.submit(
                        self.agents[aid].critique_and_refine,  # type: ignore[arg-type]
                        requirement_trunc,
                        enforce_size(current_solution.get(aid, ""), self.cfg.security.max_solution_size, label="own_solution")[0],
                        peer_bundles.get(aid, []),
                    ): aid  # type: ignore[misc]
                    for aid in self.agents.keys()
                }
                completed: Dict[str, dict] = {}

                deadline_hit_soft = False
                while True:
                    now = time.perf_counter()
                    remaining = soft_s - (now - start)
                    if remaining <= 0:
                        break
                    done, _ = concurrent.futures.wait(list(futs.keys()), timeout=remaining, return_when=concurrent.futures.FIRST_COMPLETED)
                    for d in done:
                        aid = futs.pop(d)  # type: ignore[assignment]
                        try:
                            completed[aid] = d.result().__dict__
                        except Exception as e:
                            completed[aid] = {"agent_id": aid, "decision": Decision.KEEP, "changed": False, "solution": current_solution.get(aid, ""), "reasoning": str(e), "answer_id": current_answer_id.get(aid)}
                    if len(completed) >= min_agents:
                        break
                if len(completed) < min_agents:
                    deadline_hit_soft = True
                    log_event(self.logger, LogEvent.DEADLINE_SOFT, round=r, completed=len(completed), min_agents=min_agents)

                deadline_hit_hard = False
                while futs:
                    now = time.perf_counter()
                    remaining = hard_s - (now - start)
                    if remaining <= 0:
                        deadline_hit_hard = True
                        log_event(self.logger, LogEvent.DEADLINE_HARD, round=r)
                        break
                    done, _ = concurrent.futures.wait(list(futs.keys()), timeout=remaining, return_when=concurrent.futures.FIRST_COMPLETED)
                    for d in done:
                        aid = futs.pop(d)  # type: ignore[assignment]
                        try:
                            completed[aid] = d.result().__dict__
                        except Exception as e:
                            completed[aid] = {"agent_id": aid, "decision": Decision.KEEP, "changed": False, "solution": current_solution.get(aid, ""), "reasoning": str(e), "answer_id": current_answer_id.get(aid)}

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

                    try:
                        md = res.get("metadata", {}) or {}
                        t_in = int(md.get("tokens", {}).get("prompt", 0)) if isinstance(md, dict) else 0
                        t_out = int(md.get("tokens", {}).get("output", 0)) if isinstance(md, dict) else 0
                        self._token_budget.add(t_in + t_out)
                    except Exception:
                        pass

                    round_agents[aid] = AgentRoundRecord(
                        response=TranscriptResponse(
                            agent_id=res["agent_id"],
                            solution=res["solution"],
                            reasoning=res.get("reasoning", ""),
                            decision=res["decision"],
                            changed=res.get("changed", False),
                            answer_id=res["answer_id"],
                            metadata={},
                        ),
                        peers_assigned=peers_assigned,
                        peers_seen=peers_seen,
                    )

            transcript.append(
                RoundTranscript(
                    round_index=r,
                    type=RoundType.CRITIQUE,
                    agents=round_agents,
                    scores=self.score.get_all_scores(),
                    topology_info=self.topology.info() if self.cfg.output.include_topology_info else {},
                    deadline_hit_soft=deadline_hit_soft,
                    deadline_hit_hard=deadline_hit_hard,
                )
            )
            log_event(self.logger, LogEvent.ROUND_END, round=r, type=RoundType.CRITIQUE.value)

            try:
                guard.check_round(rs)
            except BudgetExceeded:
                early_stop_reason = "round_time_budget_exceeded"
                log_event(self.logger, LogEvent.BUDGET_EXCEEDED, scope="round", round=r)
                break

        all_scores = self.score.get_all_scores()
        vm = ValidationManager(self.cfg)
        vresults, vconf = vm.validate_many(self.answer_text)
        log_event(self.logger, LogEvent.VALIDATION_DONE)
        best_ans = self._select_final(all_scores, vconf)
        final_solution = self.answer_text.get(best_ans, "")

        winning_agents = [aid for aid, ans in current_answer_id.items() if ans == best_ans]
        origin_agents: List[str] = []
        for t in transcript:
            holders = [aid for aid, rec in t.agents.items() if rec.response.answer_id == best_ans]
            if holders:
                origin_agents = holders
                break
        holders_history = {t.round_index: [aid for aid, rec in t.agents.items() if rec.response.answer_id == best_ans] for t in transcript}

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
            "metrics": self._compute_metrics(transcript, best_ans, vresults),  # type: ignore[arg-type]
        }
        return result

    def _select_final(self, scores: Dict[str, float], conf: Dict[str, float]) -> str:
        if not scores:
            return next(iter(self.answer_text.keys()))
        max_score = max(scores.values())
        top = [ans for ans, sc in scores.items() if sc == max_score]
        if len(top) == 1:
            return top[0]
        max_conf = max(conf.get(ans, 0.0) for ans in top)
        top2 = [ans for ans in top if conf.get(ans, 0.0) == max_conf]
        if len(top2) == 1:
            return top2[0]
        top2.sort()
        if self.cfg.scoring.tie_break == TieBreak.DETERMINISTIC:
            return top2[0]
        rnd = random.Random(self.cfg.scoring.random_seed)
        return rnd.choice(top2)

    def _compute_metrics(self, rounds: List[RoundTranscript], final_id: str, vresults: Dict[str, Dict[str, object]]) -> Dict[str, float]:
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

