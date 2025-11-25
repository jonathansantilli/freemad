import { BarChart, Bar, XAxis, YAxis, ResponsiveContainer, Tooltip, LabelList } from "recharts";
import type { Agent } from "@/lib/assemblyTypes";

interface ScoreBarsProps {
  agents: Agent[];
}

export function ScoreBars({ agents }: ScoreBarsProps) {
  const data = agents.map((a) => ({
    name: a.name,
    score: Number(a.currentScore?.toFixed?.(2) ?? a.currentScore ?? 0),
    fill: a.color,
  }));

  return (
    <div className="w-full h-64">
      <ResponsiveContainer>
        <BarChart data={data} layout="vertical" margin={{ left: 48, right: 24, bottom: 8 }}>
          <XAxis type="number" tick={{ fill: "#9ca3af", fontSize: 11 }} />
          <YAxis dataKey="name" type="category" width={80} tick={{ fill: "#9ca3af", fontSize: 12 }} />
          <Tooltip
            contentStyle={{ background: "#0b0f1a", border: "1px solid #1f2937" }}
            labelStyle={{ color: "#fff" }}
            formatter={(val: any) => [val, "Score"]}
          />
          <Bar dataKey="score" radius={[4, 4, 4, 4]} isAnimationActive={false}>
            {data.map((entry, index) => (
              <cell key={`cell-${index}`} fill={entry.fill} />
            ))}
            <LabelList dataKey="score" position="right" formatter={(v: number) => v.toFixed(2)} fill="#e5e7eb" fontSize={11} />
          </Bar>
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}
