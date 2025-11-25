import { useState } from "react";
import { motion } from "framer-motion";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { Send, Sparkles } from "lucide-react";

interface InputConsoleProps {
  onStartDebate: (topic: string) => void;
  isDebating: boolean;
}

export function InputConsole({ onStartDebate, isDebating }: InputConsoleProps) {
  const [topic, setTopic] = useState("");

  const handleSubmit = () => {
    const trimmed = topic.trim();
    if (trimmed) {
      onStartDebate(trimmed);
    }
  };

  return (
    <motion.div
      className="relative z-20 w-full max-w-7xl mx-auto px-6"
      initial={{ y: 50, opacity: 0 }}
      animate={{ y: 0, opacity: 1 }}
      transition={{ delay: 0.3 }}
    >
      <div className="glass-panel rounded-2xl p-1">
        <div className="bg-black/40 rounded-xl p-8 border border-white/5">
          <div className="flex items-center justify-between mb-4">
            <h2 className="text-sm font-mono text-muted-foreground tracking-widest uppercase">
              // Assembly Protocol Input
            </h2>
            <div className="flex items-center gap-2">
              <span className="w-2 h-2 rounded-full bg-green-500 animate-pulse" />
              <span className="text-xs text-green-500 font-mono">
                SYSTEM READY
              </span>
            </div>
          </div>

          <Textarea
            placeholder="Present your question to the council..."
            value={topic}
            onChange={(e) => setTopic(e.target.value)}
            className="min-h-[240px] bg-transparent border-none text-xl md:text-2xl font-light resize-none focus-visible:ring-0 placeholder:text-muted-foreground/50"
            disabled={isDebating}
          />

          <div className="flex items-center justify-between mt-6 pt-4 border-t border-white/10">
            <div className="text-xs font-mono text-muted-foreground">
              {topic.length} chars
            </div>

            <Button
              onClick={handleSubmit}
              disabled={!topic.trim() || isDebating}
              size="lg"
              className="bg-primary text-primary-foreground hover:bg-white hover:text-black transition-all duration-300 font-mono"
            >
              {isDebating ? (
                <span className="flex items-center gap-2">
                  <Sparkles className="w-4 h-4 animate-spin" />
                  Processing...
                </span>
              ) : (
                <span className="flex items-center gap-2">
                  Initialize Debate
                  <Send className="w-4 h-4" />
                </span>
              )}
            </Button>
          </div>
        </div>
      </div>

      <div className="absolute -bottom-4 left-10 right-10 h-[1px] bg-gradient-to-r from-transparent via-primary/50 to-transparent" />
    </motion.div>
  );
}
