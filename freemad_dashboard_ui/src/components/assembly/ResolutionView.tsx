import { motion, AnimatePresence } from "framer-motion";
import type {
  Agent,
  Message,
  AgentSolutionSummary,
  CritiqueEntry,
  ValidationCheck,
  SimulationConfig,
} from "@/lib/assemblyTypes";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Button } from "@/components/ui/button";
import { X, Trophy, FileText, GitCompare, Copy, ChevronsLeft, ChevronsRight, Settings2, History as HistoryIcon, ArrowLeft } from "lucide-react";
import { useState } from "react";
import { cn } from "@/lib/utils";
import { DebateStream } from "@/components/assembly/DebateStream";
import { ConfigPanel } from "@/components/assembly/ConfigPanel";
import { ScoreBars } from "@/components/assembly/ScoreBars";

interface ResolutionViewProps {
  agents: Agent[];
  messages: Message[];
  winnerId: string;
  winningAgents: string[];
  topic: string;
  finalSolution: string | null;
  solutionsByAgent: Record<string, AgentSolutionSummary>;
  critiquesByAgent: Record<string, CritiqueEntry[]>;
  validationByAgent: Record<string, ValidationCheck[]>;
  selectionExplanation: Array<Record<string, unknown>>;
  answerHolders: Record<string, string[]>;
  config: SimulationConfig;
  onConfigChange: (cfg: SimulationConfig) => void;
  onOpenRuns: () => void;
  onClose: () => void;
  onBackToLive: () => void;
}

export function ResolutionView({
  agents,
  messages,
  winnerId,
  winningAgents,
  topic,
  finalSolution,
  solutionsByAgent,
  critiquesByAgent,
  validationByAgent,
  selectionExplanation,
  answerHolders,
  config,
  onConfigChange,
  onOpenRuns,
  onClose,
  onBackToLive,
}: ResolutionViewProps) {
  const winner = agents.find((a) => a.id === winnerId) ?? agents[0];
  const [selectedAgentId, setSelectedAgentId] = useState<string>(
    winner?.id ?? ""
  );
  const [activeTab, setActiveTab] = useState<"solution" | "critique">(
    "solution"
  );
  const [showRanking, setShowRanking] = useState(true);
  const [showTranscript, setShowTranscript] = useState(true);
  const [replayAutoScroll, setReplayAutoScroll] = useState(true);

  const getAgentSolution = (agentId: string): AgentSolutionSummary => {
    const fromMap = solutionsByAgent[agentId];
    if (fromMap && fromMap.solution) {
      return fromMap;
    }
    if (agentId === winnerId && finalSolution) {
      return { solution: finalSolution, reasoning: "" };
    }
    return { solution: "", reasoning: "" };
  };

  const sortedAgents = [...agents].sort(
    (a, b) => b.currentScore - a.currentScore
  );

  const handleCopy = async () => {
    const summary = getAgentSolution(selectedAgentId);
    const text = summary.solution || summary.reasoning;
    if (!text) return;
    try {
      await navigator.clipboard.writeText(text);
    } catch {
      // ignore clipboard errors
    }
  };

  const middleWidthClass = (() => {
    if (showRanking && showTranscript) {
      return "max-w-4xl";
    }
    if (showRanking || showTranscript) {
      return "max-w-5xl";
    }
    return "max-w-7xl";
  })();

  return (
    <AnimatePresence>
      <motion.div
        initial={{ opacity: 0 }}
        animate={{ opacity: 1 }}
        exit={{ opacity: 0 }}
        className="fixed inset-0 z-50 flex flex-col bg-background/95 backdrop-blur-xl overflow-hidden"
      >
        <div className="h-16 border-b border-white/10 flex items-center justify-between px-8 bg-black/40">
          <div className="flex items-center gap-3">
            <div className="w-8 h-8 rounded bg-primary/20 flex items-center justify-center border border-primary/50">
              <div className="w-3 h-3 rounded-full bg-primary animate-pulse" />
            </div>
            <div className="flex flex-col">
              <h1 className="font-sans font-bold tracking-tight text-xl leading-none">
                FREE-MAD <span className="font-light text-muted-foreground">ORCHESTRATOR</span>
              </h1>
              <span className="text-[10px] font-mono text-muted-foreground tracking-widest uppercase">
                Resolution View
              </span>
            </div>
          </div>
          <div className="flex items-center gap-2">
            <ConfigPanel
              currentConfig={config}
              onConfigChange={onConfigChange}
              triggerClassName="h-8 px-3 rounded-full bg-black/40 border border-white/15 text-xs font-mono hover:bg-primary/20 hover:border-primary/40"
            />
            <Button
              variant="ghost"
              size="sm"
              className="h-8 px-3 rounded-full text-xs font-mono gap-2"
              onClick={onBackToLive}
            >
              <ArrowLeft className="w-3 h-3" />
              Back to live
            </Button>
            <Button
              variant="outline"
              size="sm"
              className="h-8 px-3 rounded-full text-xs font-mono gap-2"
              onClick={onOpenRuns}
            >
              <HistoryIcon className="w-3 h-3" />
              Runs
            </Button>
            <Button
              variant="outline"
              size="sm"
              className="h-8 px-3 rounded-full text-xs font-mono gap-2"
              onClick={onClose}
            >
              Close
            </Button>
          </div>
        </div>

        <div className="flex-1 flex overflow-hidden relative">
          {showRanking && (
            <div className="w-80 border-r border-white/10 bg-black/20 flex flex-col">
              <div className="p-4 border-b border-white/10 flex items-center justify-between">
                <h3 className="text-xs font-mono uppercase tracking-widest text-muted-foreground">
                  Final Rankings
                </h3>
                <Button
                  type="button"
                  size="icon"
                  variant="ghost"
                  className="h-6 w-6 rounded-full text-muted-foreground hover:text-foreground"
                  onClick={() => setShowRanking(false)}
                >
                  <ChevronsLeft className="w-3 h-3" />
                </Button>
              </div>
              <div className="p-4 pt-3 space-y-2 overflow-y-auto">
                {sortedAgents.map((agent, idx) => (
                  <button
                    key={agent.id}
                    onClick={() => setSelectedAgentId(agent.id)}
                    className={cn(
                      "w-full flex items-center gap-3 p-3 rounded-lg border transition-all text-left group",
                      selectedAgentId === agent.id
                        ? "bg-white/10 border-white/20"
                        : "bg-transparent border-transparent hover:bg-white/5"
                    )}
                  >
                    <div className="font-mono text-lg font-bold text-muted-foreground/50 w-6">
                      #{idx + 1}
                    </div>
                    <div className="relative">
                      <div className="w-8 h-8 rounded-full flex items-center justify-center border border-white/10 bg-black text-xs font-mono">
                        {agent.name.charAt(0).toUpperCase()}
                      </div>
                      {winningAgents.includes(agent.id) && (
                        <div className="absolute -top-1 -right-1 text-yellow-500">
                          <Trophy className="w-3 h-3 fill-current" />
                        </div>
                      )}
                    </div>
                    <div className="flex-1 min-w-0">
                      <div
                        className="font-bold text-sm truncate"
                        style={{ color: agent.color }}
                      >
                        {agent.name}
                      </div>
                      <div className="text-xs text-muted-foreground font-mono">
                        Score: {agent.currentScore.toFixed(2)}
                      </div>
                    </div>
                  </button>
                ))}
              </div>
            </div>
          )}

          {!showRanking && (
            <button
              type="button"
              className="absolute left-0 top-1/2 -translate-y-1/2 z-50 px-1 py-2 bg-black/60 border border-white/20 rounded-r-md text-[10px] font-mono text-muted-foreground hover:text-white"
              onClick={() => setShowRanking(true)}
            >
              <ChevronsRight className="w-3 h-3 inline-block mr-1" />
              Rankings
            </button>
          )}

          <div className="flex-1 min-w-0 flex flex-col">
            <div className="border-b border-white/10 px-8 py-6 flex items-center justify-between">
              <div className="flex items-center gap-4">
                <div className="relative">
                  <div className="w-12 h-12 rounded-full flex items-center justify-center border border-white/10 bg-black text-sm font-mono">
                    {selectedAgentId
                      ? (
                          agents.find((a) => a.id === selectedAgentId) ??
                          winner
                        ).name.charAt(0).toUpperCase()
                      : "?"}
                  </div>
                  {selectedAgentId === winnerId && (
                    <div className="absolute -bottom-2 -right-2 bg-green-500 text-black text-[10px] font-bold px-2 py-0.5 rounded-full uppercase tracking-wide border-2 border-black">
                      Winner
                    </div>
                  )}
                </div>
                <div>
                  <h1
                    className="text-3xl font-light tracking-tight"
                    style={{
                      color:
                        agents.find((a) => a.id === selectedAgentId)?.color ??
                        "hsl(var(--primary))",
                    }}
                  >
                    {
                      (
                        agents.find((a) => a.id === selectedAgentId) ??
                        winner
                      ).name
                    }
                  </h1>
                  <p className="text-muted-foreground font-mono text-sm mt-1">
                    {
                      (
                        agents.find((a) => a.id === selectedAgentId) ??
                        winner
                      ).role
                    }
                  </p>
                </div>
              </div>

              <div className="flex gap-4 items-end">
                <div className="flex flex-col items-end">
                  <span className="text-xs font-mono text-muted-foreground uppercase">
                    Total Score
                  </span>
                  <span className="text-xl font-light text-white">
                    {
                      (
                        agents.find((a) => a.id === selectedAgentId) ??
                        winner
                      ).currentScore.toFixed(2)
                    }
                  </span>
                </div>
              </div>

              <Button
                variant="outline"
                size="sm"
                onClick={handleCopy}
                className="rounded-full text-xs font-mono gap-2"
              >
                <Copy className="w-3 h-3" />
                Copy solution
              </Button>
            </div>

            <div className="flex gap-2 mb-4 border-b border-white/10 px-8 pt-4">
              <button
                type="button"
                onClick={() => setActiveTab("solution")}
                className={cn(
                  "px-4 py-2 text-sm font-medium",
                  activeTab === "solution"
                    ? "border-b-2 border-primary text-primary"
                    : "text-muted-foreground hover:text-white"
                )}
              >
                Final Solution
              </button>
              <button
                type="button"
                onClick={() => setActiveTab("critique")}
                className={cn(
                  "px-4 py-2 text-sm font-medium",
                  activeTab === "critique"
                    ? "border-b-2 border-primary text-primary"
                    : "text-muted-foreground hover:text-white"
                )}
              >
                Critique History
              </button>
            </div>

            <ScrollArea className="flex-1 px-8 pb-8">
              <div className={cn("w-full mx-auto", middleWidthClass)}>
                {activeTab === "solution" && (
                  <>
                    <div className="mb-8">
                      <h3 className="text-sm font-mono uppercase tracking-widest text-muted-foreground mb-4 flex items-center gap-2">
                        <FileText className="w-4 h-4" /> Original Prompt
                      </h3>
                      <div className="p-4 rounded-lg bg-white/5 border border-white/10 text-white/80 italic font-serif text-lg">
                        "{topic}"
                      </div>
                    </div>

                    <div className="space-y-6">
                      <h3 className="text-sm font-mono uppercase tracking-widest text-muted-foreground mb-4 flex items-center gap-2">
                        <GitCompare className="w-4 h-4" /> Final Proposed
                        Solution
                      </h3>

                      <div className="bg-black/40 border border-white/10 rounded-xl p-8 font-mono text-sm leading-relaxed shadow-2xl relative overflow-hidden">
                        <div
                          className="absolute top-0 left-0 w-1 h-full"
                          style={{
                            backgroundColor:
                              agents.find((a) => a.id === selectedAgentId)
                                ?.color ?? "hsl(var(--primary))",
                          }}
                        />
                        <p className="mb-6 text-white/90 whitespace-pre-wrap">
                          {getAgentSolution(selectedAgentId).solution ||
                            "Final solution text will appear here once available."}
                        </p>
                        {getAgentSolution(selectedAgentId).reasoning && (
                          <div className="mt-4 text-xs text-muted-foreground whitespace-pre-wrap">
                            {getAgentSolution(selectedAgentId).reasoning}
                          </div>
                        )}
                      </div>

                      <div className="grid gap-4 md:grid-cols-2">
                        <div className="bg-white/5 border border-white/10 rounded-xl p-4">
                          <h4 className="text-xs font-mono uppercase tracking-widest text-muted-foreground mb-2">
                            Validation
                          </h4>
                          <div className="space-y-2">
                            {(validationByAgent[selectedAgentId] ?? []).length === 0 && (
                              <p className="text-xs text-muted-foreground font-mono">
                                No validation data for this agent.
                              </p>
                            )}
                            {(validationByAgent[selectedAgentId] ?? []).map((v) => (
                              <div
                                key={`${selectedAgentId}-${v.name}`}
                                className="p-3 rounded-lg border border-white/10 bg-black/30"
                              >
                                <div className="flex items-center justify-between">
                                  <span className="font-mono text-sm">{v.name}</span>
                                  <span
                                    className={cn(
                                      "text-[11px] font-mono px-2 py-0.5 rounded-full border",
                                      v.passed
                                        ? "border-green-400 text-green-300 bg-green-400/10"
                                        : "border-red-400 text-red-300 bg-red-400/10"
                                    )}
                                  >
                                    {v.passed ? "PASSED" : "FAILED"}
                                  </span>
                                </div>
                                <div className="text-[11px] text-muted-foreground mt-1">
                                  Confidence: {v.confidence ?? "–"}
                                </div>
                                {v.errors.length > 0 && (
                                  <div className="text-[11px] text-red-300 mt-1 font-mono whitespace-pre-wrap">
                                    Errors: {v.errors.join("; ")}
                                  </div>
                                )}
                                {v.warnings.length > 0 && (
                                  <div className="text-[11px] text-amber-300 mt-1 font-mono whitespace-pre-wrap">
                                    Warnings: {v.warnings.join("; ")}
                                  </div>
                                )}
                              </div>
                            ))}
                          </div>
                        </div>

                        <div className="bg-white/5 border border-white/10 rounded-xl p-4">
                          <h4 className="text-xs font-mono uppercase tracking-widest text-muted-foreground mb-2">
                            Why this answer won
                          </h4>
                          {selectionExplanation.length === 0 && (
                            <p className="text-xs text-muted-foreground font-mono">
                              No selection rationale available.
                            </p>
                          )}
                          <div className="space-y-2">
                            {selectionExplanation.map((step, idx) => (
                              <div
                                key={idx}
                                className="p-3 rounded-lg border border-white/10 bg-black/30 text-[11px] font-mono text-muted-foreground"
                              >
                                <div className="text-white">
                                  {String((step as any).step ?? `Step ${idx + 1}`)}
                                </div>
                                <div>
                              Winner(s):{" "}
                              {Array.isArray((step as any).winners)
                                ? (step as any).winners
                                    .map((ans: string) => {
                                      const holders = answerHolders[ans];
                                      if (holders && holders.length) {
                                        return holders
                                          .map(
                                            (h) =>
                                              agents.find((a) => a.id === h)
                                                ?.name ?? h
                                          )
                                          .join(", ");
                                      }
                                      // fallback to agent id lookup (if winners already agent ids)
                                      const byId =
                                        agents.find((a) => a.id === ans)?.name ??
                                        ans;
                                      return byId;
                                    })
                                    .join(", ")
                                : "–"}
                                </div>
                                {"value" in step && (
                                  <div>Value: {String((step as any).value)}</div>
                                )}
                              </div>
                            ))}
                          </div>
                        </div>

                        <div className="bg-white/5 border border-white/10 rounded-xl p-4 md:col-span-2">
                          <h4 className="text-xs font-mono uppercase tracking-widest text-muted-foreground mb-2">
                            Score comparison
                          </h4>
                          <ScoreBars agents={agents} />
                        </div>
                      </div>
                    </div>
                  </>
                )}

                {activeTab === "critique" && (
                  <div className="space-y-4">
                    <h3 className="text-sm font-mono uppercase tracking-widest text-muted-foreground mb-2 flex items-center gap-2">
                      Critique Activity
                    </h3>
                    {(() => {
                      const entries =
                        critiquesByAgent[selectedAgentId] ?? [];
                      if (entries.length === 0) {
                        return (
                          <div className="text-xs text-muted-foreground">
                            No critique entries were recorded for this agent.
                          </div>
                        );
                      }
                      return entries.map((entry, idx) => (
                        <div
                          key={`${entry.round}-${idx}`}
                          className="border border-white/10 rounded-lg p-4 bg-black/40"
                        >
                          <div className="flex justify-between items-center mb-1">
                            <div className="text-xs font-mono text-muted-foreground">
                              Round {entry.round}
                            </div>
                            <div className="text-xs font-mono">
                              Decision:{" "}
                              <span className="font-semibold">
                                {entry.decision || "UNSET"}
                              </span>
                              {entry.changed && (
                                <span className="ml-2 text-amber-300">
                                  (changed)
                                </span>
                              )}
                            </div>
                          </div>
                          {entry.targetAnswerId && (
                            <div className="text-[10px] text-muted-foreground font-mono mb-1">
                              Target answer:{" "}
                              <span className="font-semibold">
                                {entry.targetAnswerId.slice(0, 12)}
                              </span>
                            </div>
                          )}
                          <div className="text-xs text-muted-foreground mb-2">
                            Peers seen: {entry.peersSeenCount} · Peers
                            assigned: {entry.peersAssignedCount}
                          </div>
                          {entry.reasoning && (
                            <div className="text-sm whitespace-pre-wrap">
                              {entry.reasoning}
                            </div>
                          )}
                        </div>
                      ));
                    })()}
                  </div>
                )}
              </div>
            </ScrollArea>
          </div>

          {showTranscript && (
            <div className="w-[360px] border-l border-white/10 bg-black/30">
              <DebateStream
                messages={messages}
                agents={agents}
                mode="replay"
                autoScroll={replayAutoScroll}
                onToggleAutoScroll={setReplayAutoScroll}
                onCollapse={() => setShowTranscript(false)}
              />
            </div>
          )}

          {!showTranscript && (
            <button
              type="button"
              className="absolute right-0 top-1/2 -translate-y-1/2 z-50 px-1 py-2 bg-black/60 border border-white/20 rounded-l-md text-[10px] font-mono text-muted-foreground hover:text-white"
              onClick={() => setShowTranscript(true)}
            >
              <ChevronsLeft className="w-3 h-3 inline-block mr-1" />
              Transcript
            </button>
          )}
        </div>
      </motion.div>
    </AnimatePresence>
  );
}
