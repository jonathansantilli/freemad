import { AnimatePresence, motion } from "framer-motion";
import type { Agent, Message } from "@/lib/assemblyTypes";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { ChevronsRight } from "lucide-react";
import { useEffect, useRef } from "react";

interface DebateStreamProps {
  messages: Message[];
  agents: Agent[];
  mode?: "live" | "replay";
  autoScroll?: boolean;
  onToggleAutoScroll?: (value: boolean) => void;
  onCollapse?: () => void;
}

export function DebateStream({
  messages,
  agents,
  mode = "live",
  autoScroll = true,
  onToggleAutoScroll,
  onCollapse,
}: DebateStreamProps) {
  const getAgent = (id: string) => agents.find((a) => a.id === id);

  const endRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    if (!autoScroll) return;
    endRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [messages.length, autoScroll]);

  return (
    <div className="w-full h-full flex flex-col">
      <div className="flex items-center justify-between p-4 border-b border-white/10 bg-black/20">
        <div className="flex flex-col">
          <h3 className="font-mono text-sm uppercase tracking-wider text-muted-foreground">
            Free-MAD Transcript
          </h3>
          <span className="text-[10px] text-muted-foreground/50 font-mono">
            Consensus-Free Protocol
          </span>
        </div>
        <div className="flex items-center gap-2">
          <div className="flex items-center gap-2">
            <Badge
              variant="outline"
              className={cn(
                "font-mono text-xs border-primary/30",
                mode === "live"
                  ? "text-primary"
                  : "text-amber-300 border-amber-400/60"
              )}
            >
              {mode === "live" ? "LIVE" : "REPLAY"}
            </Badge>
            {onToggleAutoScroll && (
              <button
                type="button"
                onClick={() => onToggleAutoScroll(!autoScroll)}
                className={cn(
                  "text-[10px] font-mono px-2 py-0.5 rounded-full border",
                  autoScroll
                    ? "border-emerald-400 text-emerald-300 bg-emerald-400/10"
                    : "border-white/20 text-muted-foreground hover:text-foreground"
                )}
              >
                {autoScroll ? "Auto-scroll: ON" : "Auto-scroll: OFF"}
              </button>
            )}
          </div>
          {onCollapse && (
            <Button
              type="button"
              variant="ghost"
              size="icon"
              className="h-6 w-6 rounded-full text-muted-foreground hover:text-foreground"
              onClick={onCollapse}
            >
              <ChevronsRight className="w-3 h-3" />
            </Button>
          )}
        </div>
      </div>

      <ScrollArea className="flex-1 p-4">
        <div className="space-y-6">
          <AnimatePresence initial={false}>
            {messages.map((msg) => {
              const agent =
                msg.agentId === "system"
                  ? ({
                      id: "system",
                      name: "System",
                      color: "hsl(var(--muted-foreground))",
                    } as Partial<Agent>)
                  : getAgent(msg.agentId);
              if (!agent) return null;

              return (
                <motion.div
                  key={msg.id}
                  initial={{ opacity: 0, x: -20 }}
                  animate={{ opacity: 1, x: 0 }}
                  className="relative pl-4 border-l-2 group"
                  style={{ borderColor: agent.color }}
                >
                  <div className="flex items-center justify-between mb-2">
                    <div className="flex items-center gap-2">
                      <span
                        className="font-mono text-xs font-bold"
                        style={{ color: agent.color ?? "hsl(var(--primary))" }}
                      >
                        {agent.name}
                      </span>
                      <Badge
                        variant="outline"
                        className={cn(
                          "text-[10px] h-5 font-mono border-white/10",
                          msg.type === "anti-conformity"
                            ? "text-red-400 bg-red-400/10"
                            : msg.type === "conformity"
                            ? "text-green-400 bg-green-400/10"
                            : "text-blue-400 bg-blue-400/10"
                        )}
                      >
                        {msg.type.replace("-", " ").toUpperCase()}
                      </Badge>
                    </div>
                    <span className="text-[10px] font-mono text-muted-foreground">
                      Round {msg.round}
                    </span>
                  </div>

                  <div className="font-mono text-sm leading-relaxed text-white/90 whitespace-pre-wrap">
                    {msg.content}
                  </div>

                  <div className="mt-2 flex items-center gap-2 opacity-0 group-hover:opacity-100 transition-opacity">
                    <span className="text-[10px] text-muted-foreground font-mono">
                      Quality Signal: {msg.scoreImpact >= 0 ? "+" : ""}
                      {msg.scoreImpact.toFixed(2)}
                    </span>
                  </div>
                </motion.div>
              );
            })}
          </AnimatePresence>

          {messages.length === 0 && (
            <div className="text-center py-10 text-muted-foreground font-mono text-xs">
              Waiting for agents to respond...
            </div>
          )}
          <div ref={endRef} />
        </div>
      </ScrollArea>
    </div>
  );
}
