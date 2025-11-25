import { useEffect, useState } from "react";
import {
  Sheet,
  SheetContent,
  SheetHeader,
  SheetTitle,
  SheetTrigger,
} from "@/components/ui/sheet";
import { Settings2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import { Slider } from "@/components/ui/slider";
import { Switch } from "@/components/ui/switch";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import type { SimulationConfig } from "@/lib/assemblyTypes";
import { Textarea } from "@/components/ui/textarea";
import { useToast } from "@/hooks/use-toast";
import yaml from "js-yaml";

interface ConfigPanelProps {
  onConfigChange: (config: SimulationConfig) => void;
  currentConfig: SimulationConfig;
  triggerClassName?: string;
}

const PRESETS: Array<{
  id: SimulationConfig["presetId"];
  name: string;
  description: string;
}> = [
  {
    id: "user_override",
    name: "User override (ALL_KEYS base)",
    description:
      "Editable copy of ALL_KEYS.yaml saved to config_examples/user_override.yaml.",
  },
  {
    id: "mock_agents",
    name: "Mock agents (local, safe)",
    description:
      "Runs against local mock agents defined in config_examples/mock_agents.yaml.",
  },
];

export function ConfigPanel({
  onConfigChange,
  currentConfig,
  triggerClassName,
}: ConfigPanelProps) {
  const triggerHasLabel = Boolean(triggerClassName);
  const [config, setConfig] = useState<SimulationConfig>(currentConfig);
  const [overrideYaml, setOverrideYaml] = useState<string>("");
  const [overrideLoading, setOverrideLoading] = useState(false);
  const [overrideError, setOverrideError] = useState<string | null>(null);
  const { toast } = useToast();

  const handleChange = (key: keyof SimulationConfig, value: unknown) => {
    const next = { ...config, [key]: value } as SimulationConfig;
    setConfig(next);
    onConfigChange(next);
  };

  const loadOverride = async () => {
    setOverrideLoading(true);
    setOverrideError(null);
    try {
      const res = await fetch("/api/config/override");
      if (!res.ok) {
        throw new Error(`status ${res.status}`);
      }
      const data = (await res.json()) as { yaml: string };
      setOverrideYaml(data.yaml ?? "");
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e);
      setOverrideError(msg);
    } finally {
      setOverrideLoading(false);
    }
  };

  const saveOverride = async () => {
    setOverrideLoading(true);
    setOverrideError(null);
    try {
      const res = await fetch("/api/config/override", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ yaml: overrideYaml }),
      });
      if (!res.ok) {
        const text = await res.text();
        throw new Error(text || `status ${res.status}`);
      }
      toast({
        title: "Config saved",
        description: "user_override.yaml updated successfully.",
      });
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e);
      setOverrideError(msg);
      toast({
        title: "Save failed",
        description: msg,
        variant: "destructive",
      });
    } finally {
      setOverrideLoading(false);
    }
  };

  useEffect(() => {
    if (config.presetId === "user_override" && !overrideYaml && !overrideLoading) {
      void loadOverride();
    }
  }, [config.presetId, overrideYaml, overrideLoading]);

  const parsedAgents = (() => {
    if (!overrideYaml) return [];
    try {
      const obj = yaml.load(overrideYaml) as { agents?: Array<{ id?: string }> } | null;
      const agents = obj?.agents ?? [];
      return agents
        .map((a) => a?.id)
        .filter((id): id is string => typeof id === "string" && Boolean(id));
    } catch {
      return [];
    }
  })();

  return (
    <Sheet>
      <SheetTrigger asChild>
        <Button
          variant="outline"
          size={triggerHasLabel ? "sm" : "icon"}
          className={
            triggerClassName ??
            "fixed top-6 right-6 z-50 rounded-full w-12 h-12 bg-black/50 backdrop-blur border-white/10 hover:bg-primary/20 hover:border-primary/50 transition-all"
          }
        >
          <Settings2 className="w-5 h-5" />
          {triggerHasLabel && (
            <span className="ml-2 font-mono text-xs uppercase tracking-wide">
              Config
            </span>
          )}
        </Button>
      </SheetTrigger>
      <SheetContent className="glass-panel border-l border-white/10 w-[400px] p-0">
        <div className="h-full flex flex-col">
          <SheetHeader className="p-6 border-b border-white/10">
            <SheetTitle className="font-mono tracking-wider uppercase text-primary">
              Assembly Configuration
            </SheetTitle>
          </SheetHeader>

          <div className="flex-1 overflow-y-auto p-6 space-y-8 text-sm">
            <div className="space-y-3">
              <Label className="text-xs font-mono uppercase text-muted-foreground">
                Agent Configuration
              </Label>
              <Select
                value={config.presetId}
                onValueChange={(v) => handleChange("presetId", v)}
              >
                <SelectTrigger className="bg-black/20 border-white/10 font-mono">
                  <SelectValue placeholder="Select preset" />
                </SelectTrigger>
                <SelectContent>
                  {PRESETS.map((preset) => (
                    <SelectItem
                      key={preset.id}
                      value={preset.id}
                      className="font-mono"
                    >
                      {preset.name}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
              <p className="text-xs text-muted-foreground">
                {
                  PRESETS.find((p) => p.id === config.presetId)
                    ?.description
                }
              </p>
              {config.presetId === "user_override" && (
                <div className="space-y-3 pt-2">
                  <div className="flex items-center justify-between">
                    <Label className="text-xs font-mono uppercase text-muted-foreground">
                      Override YAML (config_examples/user_override.yaml)
                    </Label>
                    <div className="flex items-center gap-2">
                      <Button
                        type="button"
                        variant="secondary"
                        size="sm"
                        className="text-xs font-mono"
                        disabled={overrideLoading}
                        onClick={() => void loadOverride()}
                      >
                        Reload
                      </Button>
                      <Button
                        type="button"
                        variant="outline"
                        size="sm"
                        className="text-xs font-mono"
                        disabled={overrideLoading}
                        onClick={saveOverride}
                      >
                        Save
                      </Button>
                    </div>
                  </div>
                  <Textarea
                    value={overrideYaml}
                    onChange={(e) => setOverrideYaml(e.target.value)}
                    className="h-48 font-mono text-xs bg-black/30 border-white/10"
                    placeholder="agents: ..."
                  />
                  {overrideError ? (
                    <p className="text-[11px] text-red-400 font-mono">
                      {overrideError}
                    </p>
                  ) : (
                    <p className="text-[11px] text-muted-foreground font-mono">
                      Agents:{" "}
                      {parsedAgents.length > 0
                        ? parsedAgents.join(", ")
                        : "(not parsed)"}
                    </p>
                  )}
                </div>
              )}
            </div>

            <div className="space-y-4">
              <div className="flex justify-between">
                <Label className="text-xs font-mono uppercase text-muted-foreground">
                  Debate Rounds
                </Label>
                <span className="text-xs font-mono">
                  {Math.max(1, config.rounds)}
                </span>
              </div>
              <Slider
                value={[Math.max(1, config.rounds)]}
                onValueChange={(v) => handleChange("rounds", Math.max(1, v[0]))}
                min={1}
                max={10}
                step={1}
              />
            </div>

            <div className="space-y-4">
              <div className="flex justify-between">
                <Label className="text-xs font-mono uppercase text-muted-foreground">
                  Creativity (Temp)
                </Label>
                <span className="text-xs font-mono">
                  {config.temperature.toFixed(1)}
                </span>
              </div>
              <Slider
                value={[config.temperature * 10]}
                onValueChange={(v) => handleChange("temperature", v[0] / 10)}
                max={10}
                step={1}
              />
            </div>

            <div className="space-y-4">
              <div className="flex items-center justify-between">
                <Label className="text-xs font-mono uppercase text-muted-foreground">
                  Real-time Visualization
                </Label>
                <Switch
                  checked={config.realTimeViz}
                  onCheckedChange={(v) => handleChange("realTimeViz", v)}
                />
              </div>
              <div className="flex items-center justify-between">
                <Label className="text-xs font-mono uppercase text-muted-foreground">
                  Auto-Resolve Conflicts
                </Label>
                <Switch
                  checked={config.autoResolve}
                  onCheckedChange={(v) => handleChange("autoResolve", v)}
                />
              </div>
              <div className="flex items-center justify-between">
                <Label className="text-xs font-mono uppercase text-muted-foreground">
                  Show Reasoning Chains
                </Label>
                <Switch
                  checked={config.showReasoning}
                  onCheckedChange={(v) => handleChange("showReasoning", v)}
                />
              </div>
            </div>
          </div>
        </div>
      </SheetContent>
    </Sheet>
  );
}
