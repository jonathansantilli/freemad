import { useEffect, useMemo, useRef, useState } from "react";
import { AnimatePresence, motion } from "framer-motion";
import { Pause, RotateCcw, Maximize2, History as HistoryIcon, X } from "lucide-react";
import { DebateRing } from "@/components/assembly/DebateRing";
import { InputConsole } from "@/components/assembly/InputConsole";
import { DebateStream } from "@/components/assembly/DebateStream";
import { ConfigPanel } from "@/components/assembly/ConfigPanel";
import { ScoreChart, type ScoreHistoryPoint } from "@/components/assembly/ScoreChart";
import { ResolutionView } from "@/components/assembly/ResolutionView";
import { Button } from "@/components/ui/button";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import type {
  Agent,
  Message,
  SimulationConfig,
  AgentSolutionSummary,
  CritiqueEntry,
  ValidationCheck,
} from "@/lib/assemblyTypes";
import {
  AgentStatus,
  applyEvent,
  initialSnapshot,
  type EventMessage,
  type EventPayload,
  type LiveRunResponse,
  type RunSnapshot,
} from "@/lib/liveTypes";
import { useToast } from "@/hooks/use-toast";

type HistoryRunSummary = {
  file: string;
  timestamp?: string | null;
  final_answer_id?: string | null;
  winning_agents?: string[] | null;
  rounds?: number | null;
};

const DEFAULT_CONFIG: SimulationConfig = {
  presetId: "user_override",
  customConfigPath: "",
  rounds: 3,
  temperature: 0.7,
  realTimeViz: true,
  autoResolve: true,
  showReasoning: true,
};

type LivePhase = "idle" | "generation" | "critique" | "resolution";

function mapRoundType(rt?: string | null): LivePhase {
  if (rt === "generation") return "generation";
  if (rt === "critique") return "critique";
  return "idle";
}

function colorForIndex(index: number): string {
  const palette = [
    `hsl(var(--agent-orange))`,
    `hsl(var(--agent-teal))`,
    `hsl(var(--agent-purple))`,
    `hsl(var(--agent-cyan))`,
    `hsl(var(--agent-gold))`,
  ];
  return palette[index % palette.length];
}

function deriveAgents(snapshot: RunSnapshot): Agent[] {
  const entries = Object.entries(snapshot.agents);
  return entries.map(([agentId, snap], idx) => {
    const status =
      snap.status === AgentStatus.GENERATING
        ? "speaking"
        : snap.status === AgentStatus.CRITIQUING
        ? "critiquing"
        : "idle";

    return {
      id: agentId,
      name: agentId,
      role: "",
      avatar: null,
      color: colorForIndex(idx),
      status,
      currentScore: 0,
    } as Agent;
  });
}

function deriveScoresPerAgent(
  snapshot: RunSnapshot,
  agents: Agent[]
): Record<string, number> {
  const scoresByAnswer = snapshot.scores ?? {};
  const holders = snapshot.holders ?? {};
  const perAgent: Record<string, number> = {};

  for (const [answerId, score] of Object.entries(scoresByAnswer)) {
    const hs = holders[answerId] ?? [];
    if (!hs.length) continue;
    for (const aid of hs) {
      const prev = perAgent[aid];
      if (prev === undefined || score > prev) {
        perAgent[aid] = score;
      }
    }
  }

  // Ensure all known agents have an entry
  for (const a of agents) {
    if (perAgent[a.id] === undefined) {
      perAgent[a.id] = 0;
    }
  }

  return perAgent;
}

function buildMessageFromEvent(ev: EventPayload): Message | null {
  const kind = ev.kind;
  if (!kind || !ev.agent_id || ev.round_index === undefined) {
    return null;
  }

  const base: Omit<Message, "id"> = {
    agentId: ev.agent_id,
    round: ev.round_index ?? 0,
    type: "generation",
    content: "",
    scoreImpact: 0,
  };

  if (kind === "agent_generate_started") {
    return {
      ...base,
      id: `${ev.ts_ms ?? Date.now()}-${ev.agent_id}-gen-start`,
      type: "generation",
      content: "Started generating an answer for the question.",
      scoreImpact: 0,
    };
  }

  if (kind === "agent_generate_finished") {
    return {
      ...base,
      id: `${ev.ts_ms ?? Date.now()}-${ev.agent_id}-gen`,
      type: "generation",
      content: `Completed initial answer (decision: ${ev.decision ?? "UNSET"}).`,
      scoreImpact: 0,
    };
  }

  if (kind === "agent_critique_started") {
    return {
      ...base,
      id: `${ev.ts_ms ?? Date.now()}-${ev.agent_id}-crit-start`,
      type: "anti-conformity",
      content: "Started critiquing peers' answers.",
      scoreImpact: 0,
    };
  }

  if (kind === "agent_critique_finished") {
    const changed = ev.changed ?? false;
    const decision = ev.decision ?? "UNSET";
    const mode: "conformity" | "anti-conformity" =
      changed || decision === "REJECT" || decision === "REVISE"
        ? "anti-conformity"
        : "conformity";
    return {
      ...base,
      id: `${ev.ts_ms ?? Date.now()}-${ev.agent_id}-crit`,
      type: mode,
      content: `Finished critique round (decision: ${decision}${
        changed ? ", changed opinion" : ""
      }).`,
      scoreImpact: changed ? 1 : 0,
    };
  }

  return null;
}

export function Assembly() {
  const [config, setConfig] = useState<SimulationConfig>(DEFAULT_CONFIG);
  const [topic, setTopic] = useState<string>("");
  const [snapshot, setSnapshot] = useState<RunSnapshot | null>(null);
  const [agents, setAgents] = useState<Agent[]>([]);
  const [scoreHistory, setScoreHistory] = useState<ScoreHistoryPoint[]>([]);
  const [messages, setMessages] = useState<Message[]>([]);
  const [winnerId, setWinnerId] = useState<string | null>(null);
  const [showResolution, setShowResolution] = useState(false);
  const [runId, setRunId] = useState<string | null>(null);
  const [isDebating, setIsDebating] = useState(false);
  const [runError, setRunError] = useState<string | null>(null);
  const [finalSolution, setFinalSolution] = useState<string | null>(null);
  const [solutionsByAgent, setSolutionsByAgent] = useState<
    Record<string, AgentSolutionSummary>
  >({});
  const [critiquesByAgent, setCritiquesByAgent] = useState<
    Record<string, CritiqueEntry[]>
  >({});
  const [validationByAgent, setValidationByAgent] = useState<
    Record<string, ValidationCheck[]>
  >({});
  const [answerHolders, setAnswerHolders] = useState<Record<string, string[]>>(
    {}
  );
  const [selectionExplanation, setSelectionExplanation] = useState<
    Array<Record<string, unknown>>
  >([]);
  const [resolutionMessages, setResolutionMessages] = useState<Message[]>([]);
  const [winningAgents, setWinningAgents] = useState<string[]>([]);

  const wsRef = useRef<WebSocket | null>(null);
  const { toast } = useToast();
  const [showLiveTranscript, setShowLiveTranscript] = useState(true);
  const [liveAutoScroll, setLiveAutoScroll] = useState(true);
  const [showHistory, setShowHistory] = useState(false);
  const [historyRuns, setHistoryRuns] = useState<HistoryRunSummary[]>([]);
  const [historyLoading, setHistoryLoading] = useState(false);
  const [historyError, setHistoryError] = useState<string | null>(null);

  const livePhase: LivePhase = useMemo(() => {
    if (!snapshot) return "idle";
    if (snapshot.completed) return "resolution";
    return mapRoundType(snapshot.round_type ?? null);
  }, [snapshot]);

  const activeAgentId: string | null = useMemo(() => {
    if (!snapshot) return null;
    const candidates = Object.values(snapshot.agents).filter(
      (a) =>
        a.status === AgentStatus.GENERATING ||
        a.status === AgentStatus.CRITIQUING
    );
    return candidates[0]?.agent_id ?? null;
  }, [snapshot]);

  const roundIndex = snapshot?.round_index ?? 0;

  const currentAgents: Agent[] = useMemo(() => {
    if (!snapshot) return [];
    const base = deriveAgents(snapshot);
    const scoresPerAgent = deriveScoresPerAgent(snapshot, base);
    return base.map((a) => ({
      ...a,
      currentScore: scoresPerAgent[a.id] ?? 0,
    }));
  }, [snapshot]);

  useEffect(() => {
    setAgents(currentAgents);
  }, [currentAgents]);

  const winnerFromSnapshot: string | null = useMemo(() => {
    if (!snapshot) return null;
    if (snapshot.winning_agents && snapshot.winning_agents.length > 0) {
      return snapshot.winning_agents[0];
    }
    if (agents.length === 0) return null;
    const scores = deriveScoresPerAgent(snapshot, agents);
    const best = [...agents].sort(
      (a, b) => (scores[b.id] ?? 0) - (scores[a.id] ?? 0)
    );
    return best[0]?.id ?? null;
  }, [snapshot, agents]);

  useEffect(() => {
    setWinnerId(winnerFromSnapshot);
  }, [winnerFromSnapshot]);

  const appendScoreSnapshot = (snap: RunSnapshot) => {
    if (snap.round_index === null || snap.round_index === undefined) return;
    const scoresPerAgent = deriveScoresPerAgent(snap, agents.length ? agents : deriveAgents(snap));
    const point: ScoreHistoryPoint = {
      round: snap.round_index,
      ...scoresPerAgent,
    };
    setScoreHistory((prev) => {
      const exists = prev.some((p) => p.round === point.round);
      if (exists) {
        return prev.map((p) => (p.round === point.round ? point : p));
      }
      return [...prev, point];
    });
  };

  const handleEvent = (ev: EventPayload) => {
    setSnapshot((prev) => {
      const base = prev ?? (ev.run_id ? initialSnapshot(ev.run_id) : null);
      if (!base) return prev;
      const next = applyEvent(base, ev);
      if (ev.kind === "scores_updated") {
        appendScoreSnapshot(next);
      }
      if (
        ev.kind === "run_completed" ||
        ev.kind === "run_failed" ||
        ev.kind === "run_budget_exceeded"
      ) {
        setIsDebating(false);
        if (ev.kind === "run_failed" && ev.error) {
          setRunError(ev.error);
          toast({
            title: "Run failed",
            description: ev.error,
            variant: "destructive",
          });
        }
      }
      if (ev.kind === "final_answer_selected") {
        setWinnerId(
          ev.winning_agents && ev.winning_agents.length > 0
            ? ev.winning_agents[0]
            : winnerFromSnapshot
        );
      }
      return next;
    });

    const msg =
      ev.kind === "run_started"
        ? {
            id: `${ev.ts_ms ?? Date.now()}-prep`,
            agentId: "system",
            round: 0,
            type: "generation",
            content: "Agents are preparing to debate the question.",
            scoreImpact: 0,
          }
        : buildMessageFromEvent(ev);
    if (msg) {
      setMessages((prev) => [...prev, msg]);
    }
  };

  const connectWebSocket = (id: string) => {
    const proto = window.location.protocol === "https:" ? "wss" : "ws";
    const ws = new WebSocket(`${proto}://${window.location.host}/ws/live-runs/${id}`);
    wsRef.current = ws;

    ws.onmessage = (evt) => {
      const msg = JSON.parse(evt.data) as EventMessage;
      if (!msg.event) return;
      handleEvent(msg.event);
    };
    ws.onopen = () => {
      setIsDebating(true);
    };
    ws.onerror = () => {
      setIsDebating(false);
      toast({
        title: "WebSocket error",
        description: "Lost connection to live run events.",
        variant: "destructive",
      });
    };
    ws.onclose = () => {
      wsRef.current = null;
    };
  };

  const startRun = async (requirement: string) => {
    try {
      setRunError(null);
      setMessages([]);
      setScoreHistory([]);
      setFinalSolution(null);
      setTopic(requirement);
      // Debug: log exactly what we send to the backend.
      // This stays in the browser console for your inspection.
      // eslint-disable-next-line no-console
      console.debug("[freemad-ui] startRun", {
        requirement,
        preset: config.presetId,
        customConfigPath: config.customConfigPath,
        rounds: Math.max(1, config.rounds),
      });
      const rounds = Math.max(1, config.rounds);

      const payload: Record<string, unknown> = {
        requirement,
        max_rounds: rounds,
      };
      if (config.presetId === "user_override") {
        payload.config_path = "config_examples/user_override.yaml";
      } else if (config.presetId === "mock_agents") {
        payload.config_path = "config_examples/mock_agents.yaml";
      }
      const res = await fetch("/api/live-runs", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      if (!res.ok) {
        const text = await res.text();
        setRunError(text);
        toast({
          title: "Failed to start run",
          description: text,
          variant: "destructive",
        });
        return;
      }
      const data = (await res.json()) as LiveRunResponse;
      setRunId(data.run_id);
      setSnapshot(initialSnapshot(data.run_id));
      connectWebSocket(data.run_id);
    } catch (e) {
      const message = e instanceof Error ? e.message : String(e);
      setRunError(message);
      toast({
        title: "Failed to start run",
        description: message,
        variant: "destructive",
      });
    }
  };

  const stopRun = () => {
    if (wsRef.current) {
      wsRef.current.close();
    }
    setIsDebating(false);
  };

  const loadTranscriptSolution = async (
    file?: string,
    opts?: { openResolution?: boolean }
  ) => {
    try {
      let targetFile = file;
      if (!targetFile) {
        const res = await fetch("/api/runs");
        if (!res.ok) return;
        const runs = (await res.json()) as HistoryRunSummary[];
        if (!runs.length) return;
        targetFile = runs[0].file;
      }

      const detailRes = await fetch(
        `/api/runs/${encodeURIComponent(targetFile)}`
      );
      if (!detailRes.ok) return;
      const detail = (await detailRes.json()) as {
        final_solution?: string;
        transcript?: Array<{
          round: number;
          type: string;
          agents: Record<
            string,
            {
              response?: {
                solution?: string;
                reasoning?: string;
                decision?: string;
                changed?: boolean;
                answer_id?: string;
              };
              peers_assigned_count?: number;
              peers_seen_count?: number;
            }
          >;
        }>;
        winning_agents?: string[];
      };
      setFinalSolution(detail.final_solution ?? null);
      const winning = detail.winning_agents ?? [];
      setWinningAgents(winning);
      if (winning.length > 0) {
        setWinnerId(winning[0]);
      }
      if (Array.isArray(detail.selection_explanation?.chain)) {
        setSelectionExplanation(detail.selection_explanation.chain);
      } else {
        setSelectionExplanation([]);
      }

      const transcript = detail.transcript ?? [];
      const solByAgent: Record<string, AgentSolutionSummary> = {};
      const critByAgent: Record<string, CritiqueEntry[]> = {};
      const transcriptMessages: Message[] = [];
      const agentIds = new Set<string>();
      const agentAnswer: Record<string, string | null> = {};

      for (const round of transcript) {
        const roundIndex = round.round ?? 0;
        const roundType = round.type;
        const agentsEntries = round.agents ?? {};
        for (const [agentId, rec] of Object.entries(agentsEntries)) {
          agentIds.add(agentId);
          const resp = rec.response ?? {};
          const solution = resp.solution ?? "";
          const reasoning = resp.reasoning ?? resp.solution ?? "";
          const decision = resp.decision ?? "";
          const changed = Boolean(resp.changed);
          const answerId = resp.answer_id ?? null;
          agentAnswer[agentId] = answerId;

          if (solution || reasoning) {
            solByAgent[agentId] = {
              solution,
              reasoning,
            };

            let content: string;
            if (roundType === "generation") {
              content =
                "Provided an initial answer to the question.\n\n" +
                (solution || reasoning);
            } else {
              const peerInfo =
                (rec.peers_seen_count ?? 0) > 0
                  ? ` after reviewing ${rec.peers_seen_count} peer answer(s)`
                  : "";
              content = `Submitted a critique${peerInfo}.\n\n${reasoning || solution}`;
            }

            const type: "generation" | "conformity" | "anti-conformity" =
              roundType === "generation"
                ? "generation"
                : changed || decision === "REJECT" || decision === "REVISE"
                ? "anti-conformity"
                : "conformity";

            transcriptMessages.push({
              id: `t-${roundIndex}-${agentId}-${transcriptMessages.length}`,
              agentId,
              round: roundIndex,
              type,
              content,
              scoreImpact: 0,
            });
          }

          if (roundType === "critique") {
            const entry: CritiqueEntry = {
              round: roundIndex,
              decision,
              changed,
              reasoning,
              targetAnswerId: answerId,
              peersAssignedCount: rec.peers_assigned_count ?? 0,
              peersSeenCount: rec.peers_seen_count ?? 0,
            };
            if (!critByAgent[agentId]) {
              critByAgent[agentId] = [];
            }
            critByAgent[agentId].push(entry);
          }
        }
      }

      setSolutionsByAgent(solByAgent);
      setCritiquesByAgent(critByAgent);
      const validationRaw = detail.validation ?? {};
      const validationMap: Record<string, ValidationCheck[]> = {};
      for (const [answerId, validators] of Object.entries(validationRaw)) {
        const checks: ValidationCheck[] = [];
        const validatorsObj = validators as Record<string, any>;
        for (const [name, payload] of Object.entries(validatorsObj)) {
          const p = payload as Record<string, any>;
          checks.push({
            name,
            passed: Boolean(p.passed),
            confidence:
              typeof p.confidence === "number" ? p.confidence : null,
            errors: (p.errors as string[]) ?? [],
            warnings: (p.warnings as string[]) ?? [],
            metrics: (p.metrics as Record<string, any>) ?? {},
          });
        }
        validationMap[answerId] = checks;
      }
      const validationByAgentMap: Record<string, ValidationCheck[]> = {};
      for (const [agentId, ansId] of Object.entries(agentAnswer)) {
        if (ansId && validationMap[ansId]) {
          validationByAgentMap[agentId] = validationMap[ansId];
        }
      }
      setValidationByAgent(validationByAgentMap);
      // map answer id -> agent ids
      const ansToAgents: Record<string, string[]> = {};
      for (const [agentId, ansId] of Object.entries(agentAnswer)) {
        if (ansId) {
          ansToAgents[ansId] = ansToAgents[ansId] || [];
          ansToAgents[ansId].push(agentId);
        }
      }
      setAnswerHolders(ansToAgents);
      if (agentIds.size > 0) {
        const scores: Record<string, number> = detail.scores ?? {};
        const list: Agent[] = Array.from(agentIds).map((id, idx) => {
          const ansId = agentAnswer[id];
          const score = ansId ? scores[ansId] ?? 0 : 0;
          return {
            id,
            name: id,
            role: "",
            avatar: null,
            color: colorForIndex(idx),
            status: "idle",
            currentScore: score,
          };
        });
        setAgents(list);
      }
      if (transcriptMessages.length > 0) {
        setResolutionMessages(transcriptMessages);
      }
      if (opts?.openResolution) {
        setShowResolution(true);
      }
    } catch {
      // best-effort only
    }
  };

  useEffect(() => {
    if (snapshot?.completed && config.autoResolve) {
      void loadTranscriptSolution();
      const t = setTimeout(() => setShowResolution(true), 800);
      return () => clearTimeout(t);
    }
    return;
  }, [snapshot?.completed, config.autoResolve]);

  const hasWinner = !!winnerId && !!snapshot?.completed;

  const loadHistoryRuns = async () => {
    setHistoryLoading(true);
    setHistoryError(null);
    try {
      const res = await fetch("/api/runs");
      if (!res.ok) {
        throw new Error(`failed with status ${res.status}`);
      }
      const data = (await res.json()) as HistoryRunSummary[];
      setHistoryRuns(data);
    } catch (e) {
      setHistoryError(e instanceof Error ? e.message : String(e));
    } finally {
      setHistoryLoading(false);
    }
  };

  return (
    <div className="min-h-screen w-full bg-background text-foreground overflow-hidden flex flex-col">
      <AnimatePresence>
        {showResolution && hasWinner && snapshot && (
        <ResolutionView
            agents={agents}
            messages={
              resolutionMessages.length > 0 ? resolutionMessages : messages
            }
            winnerId={winnerId!}
            winningAgents={winningAgents}
            topic={topic}
            finalSolution={finalSolution}
            solutionsByAgent={solutionsByAgent}
            critiquesByAgent={critiquesByAgent}
            validationByAgent={validationByAgent}
            selectionExplanation={selectionExplanation}
            config={config}
            onConfigChange={setConfig}
            onOpenRuns={() => {
              setShowHistory(true);
              if (!historyRuns.length && !historyLoading) {
                void loadHistoryRuns();
              }
            }}
            answerHolders={answerHolders}
            onClose={() => setShowResolution(false)}
            onBackToLive={() => setShowResolution(false)}
          />
        )}
      </AnimatePresence>

      <header className="h-16 border-b border-white/10 flex items-center px-8 justify-between bg-black/20 backdrop-blur-sm z-40">
        <div className="flex items-center gap-3">
          <div className="w-8 h-8 rounded bg-primary/20 flex items-center justify-center border border-primary/50">
            <div className="w-3 h-3 rounded-full bg-primary animate-pulse" />
          </div>
          <div className="flex flex-col">
            <h1 className="font-sans font-bold tracking-tight text-xl leading-none">
              FREE-MAD <span className="font-light text-muted-foreground">ORCHESTRATOR</span>
            </h1>
            <span className="text-[10px] font-mono text-muted-foreground tracking-widest uppercase">
              Consensus-Free Multi-Agent Debate
            </span>
          </div>
        </div>
        <div className="flex items-center gap-3">
          <ConfigPanel
            currentConfig={config}
            onConfigChange={setConfig}
            triggerClassName="h-9 px-3 rounded-full bg-black/40 border border-white/15 text-xs font-mono hover:bg-primary/20 hover:border-primary/40"
          />
          <Button
            type="button"
            variant="outline"
            size="sm"
            className="h-8 px-3 rounded-full text-xs font-mono gap-2"
            onClick={() => {
              setShowHistory(true);
              if (!historyRuns.length && !historyLoading) {
                void loadHistoryRuns();
              }
            }}
          >
            <HistoryIcon className="w-3 h-3" />
            Runs
          </Button>
          {(isDebating || hasWinner) && (
            <div className="flex items-center gap-4">
              <div className="px-3 py-1 rounded-full bg-primary/10 border border-primary/20 text-xs font-mono text-primary flex items-center gap-2">
                {isDebating ? (
                  <>
                    <span className="relative flex h-2 w-2">
                      <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-primary opacity-75" />
                      <span className="relative inline-flex rounded-full h-2 w-2 bg-primary" />
                    </span>
                    ROUND {roundIndex ?? 0} • {livePhase.toUpperCase()} MODE
                  </>
                ) : (
                  "SESSION CONCLUDED"
                )}
              </div>
              {isDebating && (
                <Button
                  variant="outline"
                  size="icon"
                  onClick={stopRun}
                  className="h-8 w-8 p-0 rounded-full"
                >
                  <Pause className="w-4 h-4" />
                </Button>
              )}
              {!isDebating && hasWinner && (
                <>
                  <Tooltip>
                    <TooltipTrigger asChild>
                      <Button
                        variant="outline"
                        size="icon"
                        onClick={() => setShowResolution(true)}
                        className="h-8 w-8 p-0 rounded-full border-green-500/50 text-green-500 hover:bg-green-500/10"
                      >
                        <Maximize2 className="w-4 h-4" />
                      </Button>
                    </TooltipTrigger>
                    <TooltipContent>View Full Resolution</TooltipContent>
                  </Tooltip>

                  <Tooltip>
                    <TooltipTrigger asChild>
                      <Button
                        variant="outline"
                        size="icon"
                        onClick={() => {
                          if (topic.trim()) startRun(topic);
                        }}
                        className="h-8 w-8 p-0 rounded-full"
                      >
                        <RotateCcw className="w-4 h-4" />
                      </Button>
                    </TooltipTrigger>
                    <TooltipContent>Restart Debate</TooltipContent>
                  </Tooltip>
                </>
              )}
            </div>
          )}
        </div>
      </header>

      <main className="flex-1 flex relative overflow-hidden">
        <div className="flex-1 relative flex flex-col items-center justify-center">
          {(isDebating || hasWinner) && (
            <div className="absolute inset-0 flex items-center justify-center z-10 top-[-50px]">
              <DebateRing
                agents={agents}
                activeAgentId={activeAgentId}
                winnerId={hasWinner ? winnerId : null}
              />
            </div>
          )}

          <AnimatePresence>
            {!isDebating && !hasWinner ? (
              <div className="z-30 mt-10 w-full">
                <InputConsole
                  onStartDebate={startRun}
                  isDebating={isDebating}
                />
              </div>
            ) : (
              <motion.div
                initial={{ opacity: 0, y: 20 }}
                animate={{ opacity: 1, y: 0 }}
                className="z-30 absolute bottom-10 left-8 text-left w-full max-w-xl"
              >
                <p className="font-mono text-xs text-muted-foreground mb-2 uppercase tracking-widest">
                  Current Inquiry
                </p>
                <h2 className="text-lg font-light leading-tight text-white/80 border-b border-white/10 pb-4 mb-4">
                  "
                  {topic.length > 50 ? `${topic.slice(0, 50)}…` : topic}"
                </h2>
                {scoreHistory.length > 0 && (
                  <motion.div
                    initial={{ opacity: 0, height: 0 }}
                    animate={{ opacity: 1, height: "auto" }}
                    className="w-full"
                  >
                    <ScoreChart history={scoreHistory} agents={agents} />
                  </motion.div>
                )}
              </motion.div>
            )}
          </AnimatePresence>

          <div className="absolute inset-0 opacity-30 pointer-events-none mix-blend-screen bg-[radial-gradient(circle_at_50%_0%,rgba(255,255,255,0.07),transparent_55%),radial-gradient(circle_at_0%_50%,rgba(147,51,234,0.08),transparent_45%),radial-gradient(circle_at_100%_50%,rgba(45,212,191,0.08),transparent_45%)]" />
        </div>

        <AnimatePresence>
          {(isDebating || hasWinner) && showLiveTranscript && (
            <motion.div
              initial={{ x: 400, opacity: 0 }}
              animate={{ x: 0, opacity: 1 }}
              exit={{ x: 400, opacity: 0 }}
              transition={{ type: "spring", damping: 30 }}
              className="w-[400px] border-l border-white/10 bg-black/40 backdrop-blur-md z-50 h-full absolute right-0 top-0 bottom-0 shadow-2xl flex flex-col"
            >
              <DebateStream
                messages={messages}
                agents={agents}
                mode="live"
                autoScroll={liveAutoScroll}
                onToggleAutoScroll={setLiveAutoScroll}
                onCollapse={() => setShowLiveTranscript(false)}
              />

              {hasWinner && (
                <div className="p-6 bg-green-900/20 border-t border-green-500/30">
                  <div className="flex items-center justify-between mb-1">
                    <div className="text-xs font-mono text-green-400 uppercase">
                      Highest Quality Score
                    </div>
                    <Button
                      variant="link"
                      size="sm"
                      className="h-auto p-0 text-green-400 hover:text-white text-xs font-mono"
                      onClick={() => setShowResolution(true)}
                    >
                      View Full Report →
                    </Button>
                  </div>
                  <div className="font-bold text-xl text-white">
                    {agents.find((a) => a.id === winnerId)?.name ??
                      "Winner"}
                  </div>
                  <div className="text-xs text-muted-foreground mt-2">
                    Selected based on reasoning trajectory across{" "}
                    {config.rounds} rounds.
                  </div>
                </div>
              )}
            </motion.div>
          )}
        </AnimatePresence>

        {(isDebating || hasWinner) && !showLiveTranscript && (
          <button
            type="button"
            className="absolute right-0 top-1/2 -translate-y-1/2 z-40 px-1 py-2 bg-black/60 border border-white/20 rounded-l-md text-[10px] font-mono text-muted-foreground hover:text-white"
            onClick={() => setShowLiveTranscript(true)}
          >
            Transcript
          </button>
        )}
      </main>

      <AnimatePresence>
        {showHistory && (
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            className="fixed inset-0 z-50 flex items-start justify-end bg-black/40 backdrop-blur-sm"
            onClick={() => setShowHistory(false)}
          >
            <motion.div
              initial={{ x: 300 }}
              animate={{ x: 0 }}
              exit={{ x: 300 }}
              transition={{ type: "spring", damping: 24 }}
              className="w-[420px] h-full bg-background border-l border-white/10 shadow-2xl flex flex-col"
              onClick={(e) => e.stopPropagation()}
            >
              <div className="p-4 border-b border-white/10 flex items-center justify-between">
                <div>
                  <h3 className="text-sm font-mono uppercase tracking-widest">
                    Past Runs
                  </h3>
                  <p className="text-[11px] text-muted-foreground">
                    Select to open resolution view
                  </p>
                </div>
                <Button
                  variant="ghost"
                  size="icon"
                  className="h-8 w-8 rounded-full"
                  onClick={() => setShowHistory(false)}
                >
                  <X className="w-4 h-4" />
                </Button>
              </div>
              <div className="flex-1 overflow-y-auto p-4 space-y-2">
                {historyLoading && (
                  <div className="text-xs font-mono text-muted-foreground">
                    Loading runs…
                  </div>
                )}
                {historyError && (
                  <div className="text-xs font-mono text-red-400">
                    {historyError}
                  </div>
                )}
                {!historyLoading && !historyRuns.length && !historyError && (
                  <div className="text-xs font-mono text-muted-foreground">
                    No transcripts found.
                  </div>
                )}
                {historyRuns.map((run) => (
                  <button
                    key={run.file}
                    className="w-full text-left p-3 rounded-lg bg-white/5 hover:bg-white/10 border border-white/10 transition-all"
                    onClick={() => {
                      void loadTranscriptSolution(run.file, { openResolution: true });
                      setShowHistory(false);
                    }}
                  >
                    <div className="flex items-center justify-between">
                      <div className="font-mono text-sm">{run.file}</div>
                      <div className="text-[11px] text-muted-foreground">
                        {run.timestamp ?? "–"}
                      </div>
                    </div>
                    <div className="text-[11px] text-muted-foreground mt-1 flex gap-2">
                      <span>Rounds: {run.rounds ?? "-"}</span>
                      {run.winning_agents && run.winning_agents.length > 0 && (
                        <span>Winner: {run.winning_agents[0]}</span>
                      )}
                    </div>
                  </button>
                ))}
              </div>
            </motion.div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}
