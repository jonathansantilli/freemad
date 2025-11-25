from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional

from freemad.run_events import RunEvent
from freemad.types import RunEventKind
from freemad.types import Decision, RoundType, StrEnum


class AgentStatus(StrEnum):
    WAITING = "waiting"
    GENERATING = "generating"
    CRITIQUING = "critiquing"
    DONE = "done"
    ERROR = "error"


@dataclass(frozen=True)
class AgentSnapshot:
    agent_id: str
    status: AgentStatus = AgentStatus.WAITING
    current_answer_id: Optional[str] = None
    changes_count: int = 0
    last_decision: Optional[Decision] = None


@dataclass(frozen=True)
class RunSnapshot:
    run_id: str
    round_index: Optional[int] = None
    round_type: Optional[RoundType] = None
    agents: Dict[str, AgentSnapshot] = field(default_factory=dict)
    scores: Dict[str, float] = field(default_factory=dict)
    holders: Dict[str, List[str]] = field(default_factory=dict)
    final_answer_id: Optional[str] = None
    winning_agents: List[str] = field(default_factory=list)
    completed: bool = False
    error: Optional[str] = None


def initial_snapshot(run_id: str) -> RunSnapshot:
    return RunSnapshot(run_id=run_id)


def _update_agent(
    agents: Dict[str, AgentSnapshot],
    agent_id: str,
    *,
    status: Optional[AgentStatus] = None,
    answer_id: Optional[str] = None,
    decision: Optional[Decision] = None,
    changed: Optional[bool] = None,
) -> Dict[str, AgentSnapshot]:
    prev = agents.get(agent_id) or AgentSnapshot(agent_id=agent_id)
    new_status = status or prev.status
    new_answer = answer_id if answer_id is not None else prev.current_answer_id
    new_decision = decision if decision is not None else prev.last_decision
    changes_count = prev.changes_count
    if changed:
        changes_count += 1
    new_agents = dict(agents)
    new_agents[agent_id] = AgentSnapshot(
        agent_id=agent_id,
        status=new_status,
        current_answer_id=new_answer,
        changes_count=changes_count,
        last_decision=new_decision,
    )
    return new_agents


def apply_event(snapshot: RunSnapshot, event: RunEvent) -> RunSnapshot:
    if event.run_id != snapshot.run_id:
        return snapshot

    # Round-level changes
    if event.kind == RunEventKind.ROUND_STARTED:
        return RunSnapshot(
            run_id=snapshot.run_id,
            round_index=event.round_index,
            round_type=event.round_type,
            agents=snapshot.agents,
            scores=snapshot.scores,
            holders=snapshot.holders,
            final_answer_id=snapshot.final_answer_id,
            winning_agents=snapshot.winning_agents,
            completed=snapshot.completed,
            error=snapshot.error,
        )

    if event.kind == RunEventKind.AGENT_GENERATE_STARTED:
        if event.agent_id is None:
            return snapshot
        agents = _update_agent(snapshot.agents, event.agent_id, status=AgentStatus.GENERATING)
        return RunSnapshot(
            run_id=snapshot.run_id,
            round_index=snapshot.round_index,
            round_type=snapshot.round_type,
            agents=agents,
            scores=snapshot.scores,
            holders=snapshot.holders,
            final_answer_id=snapshot.final_answer_id,
            winning_agents=snapshot.winning_agents,
            completed=snapshot.completed,
            error=snapshot.error,
        )

    if event.kind == RunEventKind.AGENT_GENERATE_FINISHED:
        if event.agent_id is None:
            return snapshot
        agents = _update_agent(
            snapshot.agents,
            event.agent_id,
            status=AgentStatus.WAITING,
            answer_id=event.answer_id,
            decision=event.decision,
        )
        return RunSnapshot(
            run_id=snapshot.run_id,
            round_index=snapshot.round_index,
            round_type=snapshot.round_type,
            agents=agents,
            scores=snapshot.scores,
            holders=snapshot.holders,
            final_answer_id=snapshot.final_answer_id,
            winning_agents=snapshot.winning_agents,
            completed=snapshot.completed,
            error=snapshot.error,
        )

    if event.kind == RunEventKind.AGENT_CRITIQUE_STARTED:
        if event.agent_id is None:
            return snapshot
        agents = _update_agent(snapshot.agents, event.agent_id, status=AgentStatus.CRITIQUING)
        return RunSnapshot(
            run_id=snapshot.run_id,
            round_index=snapshot.round_index,
            round_type=snapshot.round_type,
            agents=agents,
            scores=snapshot.scores,
            holders=snapshot.holders,
            final_answer_id=snapshot.final_answer_id,
            winning_agents=snapshot.winning_agents,
            completed=snapshot.completed,
            error=snapshot.error,
        )

    if event.kind == RunEventKind.AGENT_CRITIQUE_FINISHED:
        if event.agent_id is None:
            return snapshot
        agents = _update_agent(
            snapshot.agents,
            event.agent_id,
            status=AgentStatus.WAITING,
            answer_id=event.answer_id,
            decision=event.decision,
            changed=event.changed,
        )
        return RunSnapshot(
            run_id=snapshot.run_id,
            round_index=snapshot.round_index,
            round_type=snapshot.round_type,
            agents=agents,
            scores=snapshot.scores,
            holders=snapshot.holders,
            final_answer_id=snapshot.final_answer_id,
            winning_agents=snapshot.winning_agents,
            completed=snapshot.completed,
            error=snapshot.error,
        )

    if event.kind == RunEventKind.SCORES_UPDATED:
        return RunSnapshot(
            run_id=snapshot.run_id,
            round_index=snapshot.round_index,
            round_type=snapshot.round_type,
            agents=snapshot.agents,
            scores=dict(event.scores),
            holders={k: list(v) for k, v in event.holders.items()},
            final_answer_id=snapshot.final_answer_id,
            winning_agents=snapshot.winning_agents,
            completed=snapshot.completed,
            error=snapshot.error,
        )

    if event.kind == RunEventKind.FINAL_ANSWER_SELECTED:
        return RunSnapshot(
            run_id=snapshot.run_id,
            round_index=snapshot.round_index,
            round_type=snapshot.round_type,
            agents=snapshot.agents,
            scores=snapshot.scores,
            holders=snapshot.holders,
            final_answer_id=event.final_answer_id,
            winning_agents=list(event.winning_agents),
            completed=snapshot.completed,
            error=snapshot.error,
        )

    if event.kind in (RunEventKind.RUN_COMPLETED, RunEventKind.RUN_FAILED, RunEventKind.RUN_BUDGET_EXCEEDED):
        return RunSnapshot(
            run_id=snapshot.run_id,
            round_index=snapshot.round_index,
            round_type=snapshot.round_type,
            agents=snapshot.agents,
            scores=snapshot.scores,
            holders=snapshot.holders,
            final_answer_id=snapshot.final_answer_id,
            winning_agents=snapshot.winning_agents,
            completed=True,
            error=event.error if event.error is not None else snapshot.error,
        )

    return snapshot
