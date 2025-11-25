export type RunEventKindValue =
  | "run_started"
  | "run_completed"
  | "run_failed"
  | "run_budget_exceeded"
  | "round_started"
  | "round_completed"
  | "agent_generate_started"
  | "agent_generate_finished"
  | "agent_critique_started"
  | "agent_critique_finished"
  | "scores_updated"
  | "final_answer_selected";

export type RoundTypeValue = "generation" | "critique" | "validation";

export type DecisionValue = "KEEP" | "REJECT" | "REVISE" | "UNSET";

export type LiveRunResponse = {
  run_id: string;
};

export type EventPayload = {
  kind?: RunEventKindValue;
  run_id?: string;
  ts_ms?: number;
  round_index?: number;
  round_type?: RoundTypeValue;
  agent_id?: string;
  answer_id?: string;
  decision?: DecisionValue;
  changed?: boolean;
  scores?: Record<string, number>;
  holders?: Record<string, string[]>;
  winning_agents?: string[];
  final_answer_id?: string;
  selection_chain?: Array<Record<string, unknown>>;
  error?: string;
};

export type EventMessage = {
  event?: EventPayload;
};

export enum AgentStatus {
  WAITING = "waiting",
  GENERATING = "generating",
  CRITIQUING = "critiquing",
  DONE = "done",
  ERROR = "error",
}

export type AgentSnapshot = {
  agent_id: string;
  status: AgentStatus;
  current_answer_id?: string | null;
  changes_count: number;
  last_decision?: DecisionValue | null;
};

export type RunSnapshot = {
  run_id: string;
  round_index?: number | null;
  round_type?: RoundTypeValue | null;
  agents: Record<string, AgentSnapshot>;
  scores: Record<string, number>;
  holders: Record<string, string[]>;
  final_answer_id?: string | null;
  winning_agents: string[];
  completed: boolean;
  error?: string | null;
};

export function initialSnapshot(runId: string): RunSnapshot {
  return {
    run_id: runId,
    round_index: null,
    round_type: null,
    agents: {},
    scores: {},
    holders: {},
    final_answer_id: null,
    winning_agents: [],
    completed: false,
    error: null,
  };
}

function updateAgent(
  agents: Record<string, AgentSnapshot>,
  agentId: string,
  opts: {
    status?: AgentStatus;
    answer_id?: string | null;
    decision?: DecisionValue | null;
    changed?: boolean | null;
  }
): Record<string, AgentSnapshot> {
  const prev: AgentSnapshot =
    agents[agentId] ??
    ({
      agent_id: agentId,
      status: AgentStatus.WAITING,
      current_answer_id: null,
      changes_count: 0,
      last_decision: null,
    } as AgentSnapshot);

  const nextStatus = opts.status ?? prev.status;
  const nextAnswer =
    opts.answer_id !== undefined ? opts.answer_id : prev.current_answer_id;
  const nextDecision =
    opts.decision !== undefined ? opts.decision : prev.last_decision;

  let changesCount = prev.changes_count;
  if (opts.changed) {
    changesCount += 1;
  }

  return {
    ...agents,
    [agentId]: {
      agent_id: agentId,
      status: nextStatus,
      current_answer_id: nextAnswer ?? null,
      changes_count: changesCount,
      last_decision: nextDecision ?? null,
    },
  };
}

export function applyEvent(
  snapshot: RunSnapshot,
  event: EventPayload
): RunSnapshot {
  if (event.run_id && event.run_id !== snapshot.run_id) {
    return snapshot;
  }
  const kind = event.kind;
  if (!kind) return snapshot;

  if (kind === "round_started") {
    return {
      ...snapshot,
      round_index: event.round_index ?? null,
      round_type: event.round_type ?? null,
    };
  }

  if (kind === "agent_generate_started" && event.agent_id) {
    return {
      ...snapshot,
      agents: updateAgent(snapshot.agents, event.agent_id, {
        status: AgentStatus.GENERATING,
      }),
    };
  }

  if (kind === "agent_generate_finished" && event.agent_id) {
    return {
      ...snapshot,
      agents: updateAgent(snapshot.agents, event.agent_id, {
        status: AgentStatus.WAITING,
        answer_id: event.answer_id ?? null,
        decision: event.decision ?? null,
      }),
    };
  }

  if (kind === "agent_critique_started" && event.agent_id) {
    return {
      ...snapshot,
      agents: updateAgent(snapshot.agents, event.agent_id, {
        status: AgentStatus.CRITIQUING,
      }),
    };
  }

  if (kind === "agent_critique_finished" && event.agent_id) {
    return {
      ...snapshot,
      agents: updateAgent(snapshot.agents, event.agent_id, {
        status: AgentStatus.WAITING,
        answer_id: event.answer_id ?? null,
        decision: event.decision ?? null,
        changed: event.changed ?? null,
      }),
    };
  }

  if (kind === "scores_updated") {
    return {
      ...snapshot,
      scores: { ...(event.scores ?? {}) },
      holders: { ...(event.holders ?? {}) },
    };
  }

  if (kind === "final_answer_selected") {
    return {
      ...snapshot,
      final_answer_id: event.final_answer_id ?? null,
      winning_agents: [...(event.winning_agents ?? [])],
    };
  }

  if (
    kind === "run_completed" ||
    kind === "run_failed" ||
    kind === "run_budget_exceeded"
  ) {
    return {
      ...snapshot,
      completed: true,
      error: event.error ?? snapshot.error ?? null,
    };
  }

  return snapshot;
}

