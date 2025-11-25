import { motion, AnimatePresence } from "framer-motion";
import type { Agent } from "@/lib/assemblyTypes";
import { AgentAvatar } from "./AgentAvatar";
import { useEffect, useState } from "react";

interface DebateRingProps {
  agents: Agent[];
  activeAgentId: string | null;
  winnerId: string | null;
}

export function DebateRing({
  agents,
  activeAgentId,
  winnerId,
}: DebateRingProps) {
  const radius = 280;
  const [positions, setPositions] = useState<{ x: number; y: number }[]>([]);

  useEffect(() => {
    if (!agents.length) {
      setPositions([]);
      return;
    }
    const count = agents.length;
    const angleStep = (2 * Math.PI) / count;
    const newPositions = agents.map((_, i) => {
      const angle = i * angleStep - Math.PI / 2;
      return {
        x: Math.cos(angle) * radius,
        y: Math.sin(angle) * radius,
      };
    });
    setPositions(newPositions);
  }, [agents.length]);

  return (
    <div className="relative w-[600px] h-[600px] flex items-center justify-center pointer-events-none">
      <svg className="absolute inset-0 w-full h-full overflow-visible opacity-20 text-primary">
        <circle
          cx="300"
          cy="300"
          r={radius}
          fill="none"
          stroke="currentColor"
          strokeWidth="1"
          strokeDasharray="4 4"
        />

        <AnimatePresence>
          {activeAgentId &&
            agents.map((agent, i) => {
              if (agent.id === activeAgentId) return null;
              const sourceIndex = agents.findIndex(
                (a) => a.id === activeAgentId
              );
              const sourcePos =
                positions[sourceIndex] ?? { x: 0, y: 0 };
              const targetPos = positions[i] ?? { x: 0, y: 0 };

              return (
                <motion.line
                  key={`line-${activeAgentId}-${agent.id}`}
                  initial={{ pathLength: 0, opacity: 0 }}
                  animate={{ pathLength: 1, opacity: 0.4 }}
                  exit={{ pathLength: 0, opacity: 0 }}
                  x1={300 + sourcePos.x}
                  y1={300 + sourcePos.y}
                  x2={300 + targetPos.x}
                  y2={300 + targetPos.y}
                  stroke="currentColor"
                  strokeWidth="1"
                />
              );
            })}
        </AnimatePresence>
      </svg>

      {agents.map((agent, index) => {
        const pos = positions[index] ?? { x: 0, y: 0 };
        return (
          <motion.div
            key={agent.id}
            className="absolute pointer-events-auto"
            initial={{ x: 0, y: 0, opacity: 0 }}
            animate={{
              x: pos.x,
              y: pos.y,
              opacity: 1,
            }}
            transition={{
              type: "spring",
              stiffness: 100,
              damping: 20,
              delay: index * 0.05,
            }}
            style={{
              left: "50%",
              top: "50%",
              marginLeft: -50,
              marginTop: -60,
            }}
          >
            <AgentAvatar
              agent={agent}
              isActive={activeAgentId === agent.id}
              isWinner={winnerId === agent.id}
            />
          </motion.div>
        );
      })}
    </div>
  );
}

