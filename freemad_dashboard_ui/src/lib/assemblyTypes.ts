export type AgentVisualStatus =
  | "idle"
  | "thinking"
  | "speaking"
  | "critiquing"
  | "waiting";

export type DebateMode = "generation" | "conformity" | "anti-conformity";

export interface Agent {
  id: string;
  name: string;
  role: string;
  avatar: string | null;
  color: string;
  status: AgentVisualStatus;
  description?: string;
  currentScore: number;
}

export interface Message {
  id: string;
  agentId: string;
  content: string;
  round: number;
  type: DebateMode;
  scoreImpact: number;
}

export interface AgentSolutionSummary {
  solution: string;
  reasoning: string;
}

export interface CritiqueEntry {
  round: number;
  decision: string;
  changed: boolean;
  reasoning: string;
  targetAnswerId: string | null;
  peersAssignedCount: number;
  peersSeenCount: number;
}

export interface ValidationCheck {
  name: string;
  passed: boolean;
  confidence: number | null;
  errors: string[];
  warnings: string[];
  metrics: Record<string, number | string | boolean>;
}

export type AnswerHolders = Record<string, string[]>;

export interface SimulationConfig {
  // Which agent config to use for this run
  presetId: "mock_agents" | "user_override";
  // Only used when presetId requires a path (currently unused)
  customConfigPath: string;
  rounds: number;
  temperature: number;
  realTimeViz: boolean;
  autoResolve: boolean;
  showReasoning: boolean;
}
