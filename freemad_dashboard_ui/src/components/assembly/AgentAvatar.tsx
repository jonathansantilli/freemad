import { motion } from "framer-motion";
import type { Agent } from "@/lib/assemblyTypes";
import { cn } from "@/lib/utils";
import { Trophy } from "lucide-react";

interface AgentAvatarProps {
  agent: Agent;
  isActive?: boolean;
  isWinner?: boolean;
  onClick?: () => void;
}

export function AgentAvatar({
  agent,
  isActive,
  isWinner,
  onClick,
}: AgentAvatarProps) {
  const initialLetter = agent.name ? agent.name.charAt(0).toUpperCase() : "?";

  return (
    <motion.div
      className={cn(
        "relative group cursor-pointer flex flex-col items-center gap-3",
        isActive && "z-10"
      )}
      onClick={onClick}
      initial={{ scale: 0.8, opacity: 0 }}
      animate={{ scale: isWinner ? 1.2 : 1, opacity: 1 }}
      whileHover={{ scale: 1.05 }}
      transition={{ type: "spring", stiffness: 300, damping: 20 }}
    >
      {isWinner && (
        <motion.div
          initial={{ y: 10, opacity: 0 }}
          animate={{ y: -20, opacity: 1 }}
          className="absolute -top-8 text-yellow-500 drop-shadow-[0_0_10px_rgba(234,179,8,0.5)]"
        >
          <Trophy className="w-8 h-8 fill-current" />
        </motion.div>
      )}

      <div
        className="relative rounded-full p-1 transition-all duration-500"
        style={{
          boxShadow: isActive
            ? `0 0 40px -5px ${agent.color}, 0 0 15px -2px ${agent.color}`
            : isWinner
            ? `0 0 60px -5px ${agent.color}`
            : "0 0 0px 0px transparent",
        }}
      >
        <motion.div
          className="absolute inset-0 rounded-full border-2 border-transparent"
          style={{
            borderColor: agent.color,
          }}
          animate={{
            rotate: agent.status === "thinking" ? 360 : 0,
            scale:
              agent.status === "speaking" || agent.status === "critiquing"
                ? [1, 1.1, 1]
                : 1,
          }}
          transition={{
            rotate: { duration: 2, repeat: Infinity, ease: "linear" },
            scale: { duration: 2, repeat: Infinity },
          }}
        />

        <div className="relative w-20 h-20 md:w-24 md:h-24 rounded-full overflow-hidden bg-black border border-white/10 flex items-center justify-center">
          {agent.avatar ? (
            <img
              src={agent.avatar}
              alt={agent.name}
              className="w-full h-full object-cover"
            />
          ) : (
            <div
              className="w-full h-full flex items-center justify-center text-2xl font-bold"
              style={{ color: "black", backgroundColor: agent.color }}
            >
              {initialLetter}
            </div>
          )}

          {agent.status !== "idle" && (
            <div className="absolute inset-0 bg-black/40 flex items-center justify-center backdrop-blur-[2px]">
              <span className="text-[10px] font-mono uppercase tracking-wider font-bold text-white">
                {agent.status}
              </span>
            </div>
          )}
        </div>

        {agent.currentScore > 0 && (
          <motion.div
            initial={{ scale: 0 }}
            animate={{ scale: 1 }}
            className="absolute -bottom-2 -right-2 w-8 h-8 rounded-full bg-black border border-white/20 flex items-center justify-center font-mono text-xs font-bold text-white shadow-lg z-20"
            style={{ backgroundColor: agent.color }}
          >
            {Math.round(agent.currentScore)}
          </motion.div>
        )}
      </div>

      <div className="text-center">
        <div
          className="font-mono font-bold text-sm tracking-wide"
          style={{ color: agent.color }}
        >
          {agent.name}
        </div>
        {isWinner && (
          <div className="text-xs text-yellow-500 font-mono mt-1 font-bold uppercase tracking-widest">
            Highest Quality Score
          </div>
        )}
        {!isWinner && agent.role && (
          <div className="text-xs text-muted-foreground max-w-[140px] truncate">
            {agent.role}
          </div>
        )}
      </div>
    </motion.div>
  );
}

