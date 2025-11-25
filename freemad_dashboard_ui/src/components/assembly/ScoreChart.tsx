import {
  Area,
  AreaChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import type { Agent } from "@/lib/assemblyTypes";

export interface ScoreHistoryPoint {
  round: number;
  [agentId: string]: number;
}

interface ScoreChartProps {
  history: ScoreHistoryPoint[];
  agents: Agent[];
}

export function ScoreChart({ history, agents }: ScoreChartProps) {
  if (!history || history.length === 0 || agents.length === 0) return null;

  return (
    <div className="w-full h-[200px] mt-4 bg-black/20 rounded-xl border border-white/5 p-4 backdrop-blur-sm">
      <div className="flex items-center justify-between mb-2">
        <h3 className="text-xs font-mono uppercase tracking-widest text-muted-foreground">
          Reasoning Quality Trajectory
        </h3>
        <span className="text-[10px] text-muted-foreground font-mono">
          Free-MAD Scoring Metric
        </span>
      </div>
      <ResponsiveContainer width="100%" height="100%">
        <AreaChart data={history}>
          <defs>
            {agents.map((agent) => (
              <linearGradient
                key={agent.id}
                id={`gradient-${agent.id}`}
                x1="0"
                y1="0"
                x2="0"
                y2="1"
              >
                <stop
                  offset="5%"
                  stopColor={agent.color}
                  stopOpacity={0.3}
                />
                <stop
                  offset="95%"
                  stopColor={agent.color}
                  stopOpacity={0}
                />
              </linearGradient>
            ))}
          </defs>
          <CartesianGrid
            strokeDasharray="3 3"
            stroke="rgba(255,255,255,0.05)"
            vertical={false}
          />
          <XAxis
            dataKey="round"
            stroke="rgba(255,255,255,0.2)"
            tick={{ fontSize: 10, fontFamily: "JetBrains Mono, monospace" }}
            tickFormatter={(value) => `R${value as number}`}
          />
          <YAxis hide domain={[0, "auto"]} />
          <Tooltip
            contentStyle={{
              backgroundColor: "rgba(0,0,0,0.9)",
              borderColor: "rgba(255,255,255,0.1)",
              fontSize: "12px",
              fontFamily: "JetBrains Mono, monospace",
            }}
            itemStyle={{ padding: 0 }}
          />
          {agents.map((agent) => (
            <Area
              key={agent.id}
              type="monotone"
              dataKey={agent.id}
              stroke={agent.color}
              strokeWidth={2}
              fill={`url(#gradient-${agent.id})`}
              animationDuration={500}
              isAnimationActive={true}
            />
          ))}
        </AreaChart>
      </ResponsiveContainer>
    </div>
  );
}

