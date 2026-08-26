from __future__ import annotations

import dataclasses
import json
import os
import re
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional
from freemad.types import (
    ActionKind,
    CompareDirection,
    GateOp,
    JudgeParseMode,
    SupervisorIntervention,
    TaskRole,
    TieBreak,
    VariationKind,
)


class ConfigError(ValueError):
    pass


# ----------------------
# Dataclass definitions
# ----------------------


@dataclass(frozen=True)
class AgentRuntimeConfig:
    temperature: float = 0.7
    max_tokens: Optional[int] = None


@dataclass(frozen=True)
class AgentConfig:
    id: str
    type: str
    enabled: bool = True
    cli_command: Optional[str] = None
    timeout: float = 60.0  # seconds
    config: AgentRuntimeConfig = field(default_factory=AgentRuntimeConfig)
    # If True, insert mode ('generate' or 'critique') as first positional argument
    cli_mode_arg: bool = False
    # Extra CLI key-value arguments appended to the command as flags.
    # Each entry (k: v) becomes either ['--k', 'v'] or [k, 'v'] if k already starts with '-'.
    cli_args: Dict[str, str] = field(default_factory=dict)
    # Extra single flags appended verbatim (order preserved), e.g., ['--enable', '-v']
    cli_flags: List[str] = field(default_factory=list)
    # Extra positional args appended at the very end (order preserved), e.g., ['-']
    cli_positional: List[str] = field(default_factory=list)
    # Extra flags for specific call modes only: {"generating": [...], "critique": [...],
    # "task": [...]}. A debate's generate/critique calls are *thinking*, not doing --
    # against a real repository an agent given tools will explore for minutes before it
    # writes a word, and every generation call times out. `--tools ""` there, and tools
    # only for `task-*` (act), is what makes a plan debate a single bounded call.
    cli_mode_flags: Dict[str, List[str]] = field(default_factory=dict)
    roles: List[TaskRole] = field(default_factory=list)
    capabilities: List[ActionKind] = field(default_factory=list)


TopologyType = Literal["all_to_all", "k_reviewers", "ring", "star"]


@dataclass(frozen=True)
class TopologyConfig:
    type: TopologyType = "all_to_all"
    k: Optional[int] = None
    seed: int = 12345
    hub_agent: Optional[str] = None


@dataclass(frozen=True)
class DeadlinesConfig:
    soft_timeout_ms: int = 15000
    hard_timeout_ms: int = 30000
    min_agents: int = 2


@dataclass(frozen=True)
class ScoringConfig:
    weights: List[float] = field(default_factory=lambda: [20.0, 25.0, 30.0, 20.0])
    normalize: bool = True
    tie_break: TieBreak = TieBreak.DETERMINISTIC
    random_seed: int = 987654321


@dataclass(frozen=True)
class SecurityConfig:
    redact_patterns: List[str] = field(
        # `\b` matters: without it, "task-execute" contains "sk-execute" and gets
        # rewritten to "ta[REDACTED]". That was cosmetic in logs; it is not cosmetic in
        # the event store, which now runs payloads through the same redactor.
        default_factory=lambda: [
            r"\bsk-[A-Za-z0-9_\-]{8,}",
            r"(?i)api[_-]?key\s*[:=]\s*\S+",
        ]
    )
    max_requirement_size: int = 20000  # bytes/characters
    max_solution_size: int = 40000
    max_critique_size: int = 20000
    cli_use_shell: bool = False
    cli_timeout_ms: int = 60000
    cli_allowed_commands: List[str] = field(
        default_factory=lambda: [
            # Keep intentionally strict; adapters can override via config
            "zen",
            "zen-mcp",
            "claude",
            "codex",
        ]
    )


@dataclass(frozen=True)
class BudgetConfig:
    max_total_time_sec: Optional[float] = 120.0
    max_round_time_sec: Optional[float] = 30.0
    max_agent_time_sec: Optional[float] = 20.0
    max_tokens_per_agent_per_round: Optional[int] = None
    max_total_tokens: Optional[int] = None
    enforce_total_tokens: bool = (
        False  # when True, exceeding raises; default = log only
    )
    enable_token_truncation: bool = True  # control prompt token truncation only
    max_concurrent_agents: Optional[int] = None


@dataclass(frozen=True)
class OutputConfig:
    save_transcript: bool = True
    transcript_dir: str = "transcripts"
    format: Literal["json", "markdown"] = "json"
    verbose: bool = False
    include_topology_info: bool = True


@dataclass(frozen=True)
class LoggingConfig:
    level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    file: Optional[str] = None
    console: bool = True
    structured: bool = False


@dataclass(frozen=True)
class ValidationConfig:
    enable_sandbox: bool = False
    sandbox_timeout_ms: int = 500


@dataclass(frozen=True)
class CacheConfig:
    enabled: bool = False
    dir: str = ".mad_cache"
    max_entries: Optional[int] = None


@dataclass(frozen=True)
class TaskToolPolicyConfig:
    allow_web_research: bool = True
    allow_workspace_write: bool = True
    allow_local_commands: bool = True
    allowed_write_roots: List[str] = field(default_factory=lambda: ["."])
    allowed_local_commands: List[str] = field(
        default_factory=lambda: [
            "python",
            "python3",
            "pytest",
            "poetry",
            "ruff",
            "mypy",
        ]
    )
    verification_commands: List[str] = field(default_factory=list)


@dataclass(frozen=True)
class TaskConfig:
    store_path: str = ".freemad/tasks/tasks.db"
    artifacts_dir: str = ".freemad/tasks/artifacts"
    max_stage_retries: int = 2
    max_total_iterations: int = 20
    tool_policy: TaskToolPolicyConfig = field(default_factory=TaskToolPolicyConfig)


@dataclass(frozen=True)
class GatePredicateConfig:
    component: str
    op: GateOp
    value: float


@dataclass(frozen=True)
class ComparatorTermConfig:
    component: str
    direction: CompareDirection
    epsilon: float = 0.0
    # Maximum allowed regression versus best-ever on this component.
    # None means: bound by epsilon (prevents cumulative drift).
    max_regress: Optional[float] = None


@dataclass(frozen=True)
class JudgeStageConfig:
    name: str
    command: str
    timeout_sec: int = 600
    parse: JudgeParseMode = JudgeParseMode.EXIT_CODE
    provides: tuple[str, ...] = ()


@dataclass(frozen=True)
class ContainerConfig:
    """Isolation for the code the runtime executes on an agent's behalf.

    Off by default so existing configs keep working, but `evolve validate` says loudly
    when a run will execute worker-authored code on the host.
    """

    enabled: bool = False
    runtime: str = "docker"
    image: str = "python:3.13-slim"
    workdir: str = "/workspace"
    memory: Optional[str] = None
    cpus: Optional[str] = None
    # "host/path" or "host/path:/container/path", mounted read-only. For material a
    # judge legitimately needs and the worktree does not carry.
    read_only_mounts: tuple[str, ...] = ()


@dataclass(frozen=True)
class JudgeConfig:
    stages: tuple[JudgeStageConfig, ...] = ()
    gate: tuple[GatePredicateConfig, ...] = ()
    comparator: tuple[ComparatorTermConfig, ...] = ()
    protected_paths: tuple[str, ...] = ()
    network: bool = False
    container: ContainerConfig = field(default_factory=ContainerConfig)
    # Extra environment variables judge stages and worker commands may see. Everything
    # outside `sandbox.BASE_ALLOWLIST` plus these names is stripped, so the run's own
    # credentials never reach worker-authored code.
    env_passthrough: tuple[str, ...] = ()


@dataclass(frozen=True)
class EvolveVariationConfig:
    kind: VariationKind = VariationKind.SINGLE_AGENT
    agent_id: Optional[str] = None
    debate_rounds: int = 2
    debate_agent_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class EvolveSupervisorConfig:
    stall_window: int = 8
    loop_threshold: int = 3
    directions_ttl_iterations: int = 4
    max_interventions_before_human: int = 3
    intervention: SupervisorIntervention = SupervisorIntervention.DEBATE


@dataclass(frozen=True)
class EvolveStopConfig:
    max_iterations: int = 40
    max_wall_clock_minutes: int = 480
    max_total_cost_usd: Optional[float] = None
    target: tuple[GatePredicateConfig, ...] = ()


@dataclass(frozen=True)
class EvolveWorkerBudgetConfig:
    max_minutes: int = 20
    max_turns: Optional[int] = None


@dataclass(frozen=True)
class EvolveConfig:
    repo_path: str = "."
    seed_ref: str = "HEAD"
    run_branch_prefix: str = "evolve/"
    variation: EvolveVariationConfig = field(default_factory=EvolveVariationConfig)
    judge: JudgeConfig = field(default_factory=JudgeConfig)
    supervisor: EvolveSupervisorConfig = field(default_factory=EvolveSupervisorConfig)
    stop: EvolveStopConfig = field(default_factory=EvolveStopConfig)
    store_path: str = ".freemad/evolve/evolve.db"
    context_budget_chars: int = 8000
    worker_budget: EvolveWorkerBudgetConfig = field(
        default_factory=EvolveWorkerBudgetConfig
    )
    knowledge_paths: tuple[str, ...] = ()


@dataclass(frozen=True)
class Config:
    agents: List[AgentConfig]
    topology: TopologyConfig = field(default_factory=TopologyConfig)
    deadlines: DeadlinesConfig = field(default_factory=DeadlinesConfig)
    scoring: ScoringConfig = field(default_factory=ScoringConfig)
    security: SecurityConfig = field(default_factory=SecurityConfig)
    budget: BudgetConfig = field(default_factory=BudgetConfig)
    output: OutputConfig = field(default_factory=OutputConfig)
    logging: LoggingConfig = field(default_factory=LoggingConfig)
    validation: ValidationConfig = field(default_factory=ValidationConfig)
    cache: CacheConfig = field(default_factory=CacheConfig)
    task: TaskConfig = field(default_factory=TaskConfig)
    evolve: EvolveConfig = field(default_factory=EvolveConfig)


# ----------------------
# Default config factory
# ----------------------


def default_agents() -> List[AgentConfig]:
    return [
        AgentConfig(
            id="claude",
            type="claude_code",
            enabled=True,
            cli_command=None,
            timeout=60.0,
            config=AgentRuntimeConfig(temperature=0.7, max_tokens=None),
        ),
        AgentConfig(
            id="codex",
            type="openai_codex",
            enabled=True,
            cli_command=None,
            timeout=60.0,
            config=AgentRuntimeConfig(temperature=0.7, max_tokens=None),
        ),
    ]


def default_config() -> Config:
    return Config(agents=default_agents())


# ----------------------
# Dict conversion helpers
# ----------------------


def _asdict_cfg(cfg: Any) -> Dict[str, Any]:
    if dataclasses.is_dataclass(cfg):
        return {k: _asdict_cfg(v) for k, v in dataclasses.asdict(cfg).items()}  # type: ignore[arg-type]
    if isinstance(cfg, list):
        return [_asdict_cfg(x) for x in cfg]  # type: ignore[return-value]
    return cfg  # type: ignore[return-value]


def to_dict(cfg: Config) -> Dict[str, Any]:
    return _asdict_cfg(cfg)


# ----------------------
# Validation
# ----------------------


def _validate_agents(agents: List[AgentConfig]) -> None:
    if len(agents) < 2:
        raise ConfigError("config.agents must contain at least 2 agents")

    ids = [a.id for a in agents]
    if len(ids) != len(set(ids)):
        raise ConfigError("config.agents ids must be unique")

    for a in agents:
        if not a.id or not a.type:
            raise ConfigError("each agent requires non-empty id and type")
        if a.timeout is not None and a.timeout <= 0:
            raise ConfigError(f"agent {a.id} timeout must be > 0")
        if any(not isinstance(role, TaskRole) for role in a.roles):
            raise ConfigError(f"agent {a.id} roles must be valid task roles")
        if any(not isinstance(capability, ActionKind) for capability in a.capabilities):
            raise ConfigError(f"agent {a.id} capabilities must be valid action kinds")


def _validate_topology(top: TopologyConfig, agents: List[AgentConfig]) -> None:
    if top.type not in ("all_to_all", "k_reviewers", "ring", "star"):
        raise ConfigError(f"invalid topology.type: {top.type}")

    n = len(agents)
    if top.type == "k_reviewers":
        if top.k is None:
            raise ConfigError("topology.k required for k_reviewers")
        if not (1 <= top.k <= max(1, n - 1)):
            raise ConfigError("topology.k must be in [1, N-1]")
    if top.type == "star":
        if not top.hub_agent:
            raise ConfigError("topology.hub_agent required for star topology")
        if top.hub_agent not in {a.id for a in agents}:
            raise ConfigError("topology.hub_agent must match an agent id")


def _validate_deadlines(d: DeadlinesConfig, agents: List[AgentConfig]) -> None:
    if not (d.soft_timeout_ms > 0 and d.hard_timeout_ms > 0):
        raise ConfigError("deadlines timeouts must be positive")
    if d.soft_timeout_ms >= d.hard_timeout_ms:
        raise ConfigError("deadlines.soft_timeout_ms must be < hard_timeout_ms")
    if not (1 <= d.min_agents <= len(agents)):
        raise ConfigError("deadlines.min_agents must be in [1, N]")


def _validate_scoring(s: ScoringConfig) -> None:
    if len(s.weights) != 4:
        raise ConfigError("scoring.weights must have length 4 [w1,w2,w3,w4]")
    if any((not isinstance(w, (int, float)) or w < 0) for w in s.weights):
        raise ConfigError("scoring.weights must be non-negative numbers")
    # tie_break is an enum by construction


def _validate_security(sec: SecurityConfig) -> None:
    if sec.cli_use_shell:
        # Disallowed by spec unless explicitly overridden later
        raise ConfigError("security.cli_use_shell must be False per spec")
    if sec.cli_timeout_ms <= 0:
        raise ConfigError("security.cli_timeout_ms must be > 0")
    if not all(isinstance(cmd, str) and cmd for cmd in sec.cli_allowed_commands):
        raise ConfigError("security.cli_allowed_commands must be non-empty strings")
    # Basic sanity for redact patterns
    for pat in sec.redact_patterns:
        try:
            re.compile(pat)
        except re.error as e:
            raise ConfigError(f"invalid redact pattern: {pat}: {e}") from e


def _validate_budget(b: BudgetConfig) -> None:
    nums = {
        "max_total_time_sec": b.max_total_time_sec,
        "max_round_time_sec": b.max_round_time_sec,
        "max_agent_time_sec": b.max_agent_time_sec,
    }
    for name, val in nums.items():
        if val is not None and val <= 0:
            raise ConfigError(f"budget.{name} must be > 0 if set")
    for name, val in (
        ("max_tokens_per_agent_per_round", b.max_tokens_per_agent_per_round),
        ("max_total_tokens", b.max_total_tokens),
        ("max_concurrent_agents", b.max_concurrent_agents),
    ):
        if val is not None and val <= 0:
            raise ConfigError(f"budget.{name} must be > 0 if set")


def _validate_output(out: OutputConfig) -> None:
    if out.format not in ("json", "markdown"):
        raise ConfigError("output.format must be json|markdown")
    if not out.transcript_dir:
        raise ConfigError("output.transcript_dir must be non-empty")


def _validate_logging(log: LoggingConfig) -> None:
    if log.level not in ("DEBUG", "INFO", "WARNING", "ERROR"):
        raise ConfigError("logging.level must be DEBUG|INFO|WARNING|ERROR")


def _validate_task(task: TaskConfig) -> None:
    if not task.store_path:
        raise ConfigError("task.store_path must be non-empty")
    if not task.artifacts_dir:
        raise ConfigError("task.artifacts_dir must be non-empty")
    if task.max_stage_retries < 0:
        raise ConfigError("task.max_stage_retries must be >= 0")
    if task.max_total_iterations <= 0:
        raise ConfigError("task.max_total_iterations must be > 0")
    if not all(
        isinstance(root, str) and root.strip()
        for root in task.tool_policy.allowed_write_roots
    ):
        raise ConfigError(
            "task.tool_policy.allowed_write_roots must be non-empty strings"
        )
    if not all(
        isinstance(cmd, str) and cmd.strip()
        for cmd in task.tool_policy.allowed_local_commands
    ):
        raise ConfigError(
            "task.tool_policy.allowed_local_commands must be non-empty strings"
        )
    if not all(
        isinstance(cmd, str) and cmd.strip()
        for cmd in task.tool_policy.verification_commands
    ):
        raise ConfigError(
            "task.tool_policy.verification_commands must be non-empty strings"
        )


_GATE_OPS = tuple(op.value for op in GateOp)
_ENV_NAME_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")

# Passing any of these through hands a worker control of the process the judge starts,
# which defeats the point of scrubbing in the first place.
_ENV_PASSTHROUGH_DENYLIST = frozenset(
    {
        "LD_PRELOAD",
        "LD_LIBRARY_PATH",
        "LD_AUDIT",
        "DYLD_INSERT_LIBRARIES",
        "DYLD_LIBRARY_PATH",
        "PYTHONPATH",
        "PYTHONSTARTUP",
        "PYTHONHOME",
        "PYTHONEXECUTABLE",
        "BASH_ENV",
        "ENV",
        "NODE_OPTIONS",
    }
)


def _validate_relative_path(path_str: str, label: str) -> None:
    if not path_str or not path_str.strip():
        raise ConfigError(f"evolve.{label} entries must be non-empty strings")
    if "\x00" in path_str:
        raise ConfigError(
            f"evolve.{label} entries must not contain null bytes: {path_str!r}"
        )
    if path_str.strip() in {".", "./"}:
        # The worktree root itself: restoring it would mean deleting the checkout.
        raise ConfigError(
            f"evolve.{label} entries must name a path inside the repo, not '.'"
        )
    if any(ch in path_str for ch in "*?[]"):
        # git glob-expands these in `ls-tree`, while the Python side treats the same
        # string as a literal path -- so the entry looks protected and protects nothing.
        raise ConfigError(
            f"evolve.{label} entries must not contain glob characters: {path_str}"
        )
    if path_str.startswith(":"):
        # `:(exclude)tests`, `:!tests` and friends are git pathspec magic.
        raise ConfigError(
            f"evolve.{label} entries must not use git pathspec magic: {path_str}"
        )
    p = Path(path_str)
    if p.is_absolute():
        raise ConfigError(f"evolve.{label} entries must be relative paths: {path_str}")
    if ".." in p.parts:
        raise ConfigError(
            f"evolve.{label} entries must not traverse upward: {path_str}"
        )


def _validate_gate_predicates(
    gate: tuple[GatePredicateConfig, ...], provided: set[str], label: str
) -> None:
    for pred in gate:
        if not pred.component:
            raise ConfigError(f"evolve.{label} predicate component must be non-empty")
        if pred.component not in provided:
            raise ConfigError(
                f"evolve.{label} references component '{pred.component}' "
                f"not provided by any judge stage"
            )
        if not isinstance(pred.value, (int, float)):
            raise ConfigError(f"evolve.{label} predicate value must be a number")


def _validate_evolve(evolve: EvolveConfig, agents: List[AgentConfig]) -> None:
    if not evolve.repo_path:
        raise ConfigError("evolve.repo_path must be non-empty")
    if not evolve.seed_ref:
        raise ConfigError("evolve.seed_ref must be non-empty")
    if not evolve.run_branch_prefix:
        raise ConfigError("evolve.run_branch_prefix must be non-empty")
    if evolve.context_budget_chars <= 0:
        raise ConfigError("evolve.context_budget_chars must be > 0")

    # Variation
    var = evolve.variation
    in_use = bool(evolve.judge.stages)
    if var.kind not in (VariationKind.SINGLE_AGENT, VariationKind.DEBATE):
        raise ConfigError("evolve.variation.kind must be single_agent|debate")
    if (
        in_use
        and var.kind == VariationKind.SINGLE_AGENT
        and not (var.agent_id and var.agent_id.strip())
    ):
        raise ConfigError(
            "evolve.variation.agent_id is required for single_agent variation"
        )
    if var.kind == VariationKind.DEBATE and var.debate_rounds < 1:
        raise ConfigError("evolve.variation.debate_rounds must be >= 1")
    if var.debate_agent_ids:
        if len(set(var.debate_agent_ids)) != len(var.debate_agent_ids):
            raise ConfigError("evolve.variation.debate_agent_ids must be unique")
        if len(var.debate_agent_ids) < 2:
            raise ConfigError(
                "evolve.variation.debate_agent_ids needs at least 2 agents to debate"
            )
        enabled = {a.id for a in agents if a.enabled}
        missing = [i for i in var.debate_agent_ids if i not in enabled]
        if missing:
            # Otherwise the debate is constructed with too few agents, every iteration
            # fails as WORKER_FAILED, and the run burns its whole budget in silence.
            raise ConfigError(
                f"evolve.variation.debate_agent_ids names no enabled agent: "
                f"{', '.join(missing)}"
            )
    if in_use and not evolve.judge.comparator:
        raise ConfigError(
            "evolve.judge.comparator is required when judge stages are configured"
        )

    # Judge stages: unique names, sane timeouts, declared provisions.
    stage_names = [s.name for s in evolve.judge.stages]
    if len(stage_names) != len(set(stage_names)):
        raise ConfigError("evolve.judge stage names must be unique")
    provided: set[str] = set()
    for stage in evolve.judge.stages:
        if not stage.name or not stage.name.strip():
            raise ConfigError("evolve.judge stage names must be non-empty")
        if not stage.command or not stage.command.strip():
            raise ConfigError(
                f"evolve.judge stage {stage.name} command must be non-empty"
            )
        if stage.timeout_sec <= 0:
            raise ConfigError(
                f"evolve.judge stage {stage.name} timeout_sec must be > 0"
            )
        if stage.parse not in ("exit_code", "json_stdout"):
            raise ConfigError(
                f"evolve.judge stage {stage.name} parse must be exit_code|json_stdout"
            )
        if stage.parse == "exit_code" and stage.provides:
            raise ConfigError(
                f"evolve.judge stage {stage.name}: exit_code stages cannot provide components"
            )
        if stage.parse == "json_stdout":
            if not stage.provides:
                raise ConfigError(
                    f"evolve.judge stage {stage.name}: json_stdout stages must declare provides"
                )
            for comp in stage.provides:
                if not comp or not comp.strip():
                    raise ConfigError(
                        f"evolve.judge stage {stage.name}: component names must be non-empty"
                    )
                if comp in provided:
                    raise ConfigError(
                        f"evolve.judge component '{comp}' provided by multiple stages"
                    )
                provided.add(comp)

    if provided and not evolve.judge.protected_paths:
        # evolve.md section 2.2: every scored component must derive from at least one
        # protected stage. Which stage that is takes a heuristic (hence a warning in
        # `evolve validate`), but "no protected paths at all" needs none: the worker can
        # rewrite every scorer.
        raise ConfigError(
            "evolve.judge declares scored components but no protected_paths; "
            "the measurement would be fully worker-editable"
        )

    _validate_gate_predicates(evolve.judge.gate, provided, "judge.gate")

    # Comparator: ordered terms over provided components with finite tolerances.
    if evolve.judge.comparator:
        seen_components = set()
        for term in evolve.judge.comparator:
            if term.component not in provided:
                raise ConfigError(
                    f"evolve.judge.comparator references component '{term.component}' "
                    f"not provided by any judge stage"
                )
            if term.component in seen_components:
                raise ConfigError(
                    f"evolve.judge.comparator lists component '{term.component}' more than once"
                )
            seen_components.add(term.component)
            if term.direction not in ("maximize", "minimize"):
                raise ConfigError(
                    f"evolve.judge.comparator[{term.component}] direction must be maximize|minimize"
                )
            if term.epsilon < 0:
                raise ConfigError(
                    f"evolve.judge.comparator[{term.component}] epsilon must be >= 0"
                )
            if term.max_regress is not None and term.max_regress < 0:
                raise ConfigError(
                    f"evolve.judge.comparator[{term.component}] max_regress must be >= 0 if set"
                )

    # Container isolation.
    container = evolve.judge.container
    if container.enabled:
        if not container.image.strip():
            raise ConfigError(
                "evolve.judge.container.image must be non-empty when enabled"
            )
        if not container.runtime.strip():
            raise ConfigError(
                "evolve.judge.container.runtime must be non-empty when enabled"
            )
        if not container.workdir.startswith("/"):
            raise ConfigError(
                f"evolve.judge.container.workdir must be an absolute container path: "
                f"{container.workdir}"
            )
        for mount in container.read_only_mounts:
            host = mount.partition(":")[0]
            if not host.strip():
                raise ConfigError(
                    "evolve.judge.container.read_only_mounts entries need a host path"
                )

    # Env passthrough: plausible variable names, no duplicates, no secrets by accident.
    for name in evolve.judge.env_passthrough:
        if not name or not name.strip():
            raise ConfigError("evolve.judge.env_passthrough entries must be non-empty")
        if not _ENV_NAME_RE.fullmatch(name):
            raise ConfigError(
                f"evolve.judge.env_passthrough entry is not a variable name: {name}"
            )
        if name in _ENV_PASSTHROUGH_DENYLIST:
            raise ConfigError(
                f"evolve.judge.env_passthrough must not include '{name}': it lets a "
                f"worker steer the interpreter the judge runs, which is the surface the "
                f"allowlist exists to close"
            )
    if len(evolve.judge.env_passthrough) != len(set(evolve.judge.env_passthrough)):
        raise ConfigError("evolve.judge.env_passthrough entries must be unique")

    # Protected paths: repo-relative, no traversal, unique.
    for path_str in evolve.judge.protected_paths:
        _validate_relative_path(path_str, "judge.protected_paths")
    if len(evolve.judge.protected_paths) != len(set(evolve.judge.protected_paths)):
        raise ConfigError("evolve.judge.protected_paths entries must be unique")

    # Supervisor knobs.
    sup = evolve.supervisor
    if sup.stall_window < 1:
        raise ConfigError("evolve.supervisor.stall_window must be >= 1")
    if sup.loop_threshold < 1:
        raise ConfigError("evolve.supervisor.loop_threshold must be >= 1")
    if sup.directions_ttl_iterations < 1:
        raise ConfigError("evolve.supervisor.directions_ttl_iterations must be >= 1")
    if sup.max_interventions_before_human < 1:
        raise ConfigError(
            "evolve.supervisor.max_interventions_before_human must be >= 1"
        )
    if sup.intervention not in ("debate", "single_agent"):
        raise ConfigError("evolve.supervisor.intervention must be debate|single_agent")

    # Stop conditions.
    stop = evolve.stop
    if stop.max_iterations < 1:
        raise ConfigError("evolve.stop.max_iterations must be >= 1")
    if stop.max_wall_clock_minutes < 1:
        raise ConfigError("evolve.stop.max_wall_clock_minutes must be >= 1")
    if stop.max_total_cost_usd is not None and stop.max_total_cost_usd <= 0:
        raise ConfigError("evolve.stop.max_total_cost_usd must be > 0 if set")
    _validate_gate_predicates(stop.target, provided, "stop.target")

    # Worker budget.
    if evolve.worker_budget.max_minutes < 1:
        raise ConfigError("evolve.worker_budget.max_minutes must be >= 1")
    if (
        evolve.worker_budget.max_turns is not None
        and evolve.worker_budget.max_turns < 1
    ):
        raise ConfigError("evolve.worker_budget.max_turns must be >= 1 if set")

    # Knowledge paths: read-only reference material, repo-relative.
    for path_str in evolve.knowledge_paths:
        _validate_relative_path(path_str, "knowledge_paths")
    if len(evolve.knowledge_paths) != len(set(evolve.knowledge_paths)):
        raise ConfigError("evolve.knowledge_paths entries must be unique")


def validate_config(cfg: Config) -> None:
    _validate_agents(cfg.agents)
    _validate_topology(cfg.topology, cfg.agents)
    _validate_deadlines(cfg.deadlines, cfg.agents)
    _validate_scoring(cfg.scoring)
    _validate_security(cfg.security)
    _validate_budget(cfg.budget)
    _validate_output(cfg.output)
    _validate_logging(cfg.logging)
    # validation config sanity
    if cfg.validation.sandbox_timeout_ms <= 0:
        raise ConfigError("validation.sandbox_timeout_ms must be > 0")
    # cache config
    if not cfg.cache.dir:
        raise ConfigError("cache.dir must be non-empty")
    _validate_task(cfg.task)
    _validate_evolve(cfg.evolve, cfg.agents)


# ----------------------
# Loading & merging
# ----------------------


def _deep_update(base: Dict[str, Any], override: Dict[str, Any]) -> Dict[str, Any]:
    for k, v in override.items():
        if isinstance(v, dict) and isinstance(base.get(k), dict):
            base[k] = _deep_update(dict(base[k]), v)
        else:
            base[k] = v
    return base


def _maybe_parse_yaml(text: str) -> Dict[str, Any]:
    """Parse YAML if PyYAML is installed; otherwise raise a helpful error."""
    try:
        import yaml  # type: ignore

        data = yaml.safe_load(text) or {}
        if not isinstance(data, dict):
            raise ConfigError("YAML root must be a mapping")
        return data
    except Exception as e:
        if isinstance(e, ModuleNotFoundError):
            raise ConfigError(
                "PyYAML is not installed; provide JSON config or install pyyaml"
            ) from e
        raise ConfigError(f"could not parse YAML config: {e}") from e


def _load_config_file(path: Path) -> Dict[str, Any]:
    # codeql[py/path-injection] `path` is normalized and validated by `_resolve_existing_config_file`.
    text = path.read_text(encoding="utf-8")
    ext = path.suffix.lower()
    if ext in (".yaml", ".yml"):
        return _maybe_parse_yaml(text)
    if ext == ".json":
        data = json.loads(text or "{}")
        if not isinstance(data, dict):
            raise ConfigError("JSON root must be an object")
        return data
    # Try YAML first, then JSON as a fallback
    try:
        return _maybe_parse_yaml(text)
    except ConfigError:
        try:
            data = json.loads(text or "{}")
            if not isinstance(data, dict):
                raise ConfigError("config root must be a mapping/object")
            return data
        except json.JSONDecodeError as e:
            raise ConfigError(f"could not parse config file {path}: {e}") from e


def _coerce_agent(obj: Dict[str, Any]) -> AgentConfig:
    return AgentConfig(
        id=str(obj.get("id", "")).strip(),
        type=str(obj.get("type", "")).strip(),
        enabled=bool(obj.get("enabled", True)),
        cli_command=(
            str(obj["cli_command"]).strip() if obj.get("cli_command") else None
        ),
        timeout=float(obj.get("timeout", 60.0)),
        config=AgentRuntimeConfig(
            temperature=float(obj.get("config", {}).get("temperature", 0.7)),
            max_tokens=(
                int(obj.get("config", {}).get("max_tokens"))
                if obj.get("config", {}).get("max_tokens") is not None
                else None
            ),
        ),
        cli_mode_arg=bool(obj.get("cli_mode_arg", False)),
        cli_args={
            str(k): str(v) for k, v in dict(obj.get("cli_args", {}) or {}).items()
        },
        cli_flags=[str(x) for x in list(obj.get("cli_flags", []) or [])],
        cli_positional=[str(x) for x in list(obj.get("cli_positional", []) or [])],
        cli_mode_flags={
            str(k): [str(x) for x in list(v or [])]
            for k, v in dict(obj.get("cli_mode_flags", {}) or {}).items()
        },
        roles=[_coerce_task_role(x) for x in list(obj.get("roles", []) or [])],
        capabilities=[
            _coerce_action_kind(x) for x in list(obj.get("capabilities", []) or [])
        ],
    )


def _opt_int(v: Any) -> Optional[int]:
    if v is None:
        return None
    return int(v)


def _opt_float(v: Any) -> Optional[float]:
    if v is None:
        return None
    return float(v)


def _opt_str(v: Any) -> Optional[str]:
    if v is None:
        return None
    s = str(v).strip()
    return s if s else None


def output_or(d: Dict[str, Any], key: str, default: Any) -> Any:
    val = d.get(key, default)
    return val


def _coerce_tiebreak(v: Any) -> TieBreak:
    if isinstance(v, TieBreak):
        return v
    s = str(v).strip().lower()
    if s == TieBreak.DETERMINISTIC.value:
        return TieBreak.DETERMINISTIC
    if s == TieBreak.RANDOM.value:
        return TieBreak.RANDOM
    raise ConfigError("scoring.tie_break must be deterministic|random")


def _coerce_task_role(v: Any) -> TaskRole:
    if isinstance(v, TaskRole):
        return v
    s = str(v).strip().lower()
    for role in TaskRole:
        if role.value == s:
            return role
    raise ConfigError(f"invalid task role: {v}")


def _coerce_action_kind(v: Any) -> ActionKind:
    if isinstance(v, ActionKind):
        return v
    s = str(v).strip().lower()
    for action in ActionKind:
        if action.value == s:
            return action
    raise ConfigError(f"invalid action kind: {v}")


def _coerce_enum(value: Any, enum_cls: Any, label: str) -> Any:
    """Config strings become enum members at the boundary, per AGENTS.md."""
    try:
        return enum_cls(str(value).strip())
    except ValueError:
        allowed = "|".join(m.value for m in enum_cls)
        raise ConfigError(f"{label} must be {allowed}") from None


def _coerce_variation_kind(v: Any) -> VariationKind:
    if isinstance(v, VariationKind):
        return v
    s = str(v).strip().lower()
    for kind in VariationKind:
        if kind.value == s:
            return kind
    raise ConfigError("evolve.variation.kind must be single_agent|debate")


def _coerce_gate_predicates(items: Any, label: str) -> tuple[GatePredicateConfig, ...]:
    if not items:
        return ()
    if not isinstance(items, list):
        raise ConfigError(f"evolve.{label} must be a list")
    predicates: List[GatePredicateConfig] = []
    for item in items:
        if not isinstance(item, dict):
            raise ConfigError(f"evolve.{label} entries must be mappings")
        component = str(item.get("component", "")).strip()
        raw_op = str(item.get("op", GateOp.GTE.value))
        if raw_op not in _GATE_OPS:
            raise ConfigError(f"evolve.{label} op must be one of {_GATE_OPS}")
        predicates.append(
            GatePredicateConfig(
                component=component,
                op=GateOp(raw_op),
                value=float(item.get("value", 0.0)),
            )
        )
    return tuple(predicates)


def _coerce_comparator(items: Any) -> tuple[ComparatorTermConfig, ...]:
    if not items:
        return ()
    if not isinstance(items, list):
        raise ConfigError("evolve.judge.comparator must be a list")
    terms: List[ComparatorTermConfig] = []
    for item in items:
        if not isinstance(item, dict):
            raise ConfigError("evolve.judge.comparator entries must be mappings")
        max_regress_raw = item.get("max_regress")
        terms.append(
            ComparatorTermConfig(
                component=str(item.get("component", "")).strip(),
                direction=_coerce_enum(
                    item.get("direction", CompareDirection.MAXIMIZE.value),
                    CompareDirection,
                    "evolve.judge.comparator direction",
                ),
                epsilon=float(item.get("epsilon", 0.0)),
                max_regress=(
                    float(max_regress_raw) if max_regress_raw is not None else None
                ),
            )
        )
    return tuple(terms)


def _coerce_container(raw: Any) -> ContainerConfig:
    data = dict(raw or {})
    return ContainerConfig(
        enabled=bool(data.get("enabled", False)),
        # An ABSENT key gets the default; a key the operator wrote as blank is kept
        # blank so validation rejects it. Substituting a default for something someone
        # explicitly typed is how a config comes to mean something other than it says.
        runtime=str(data.get("runtime", "docker")).strip(),
        image=str(data.get("image", "python:3.13-slim")).strip(),
        workdir=str(data.get("workdir", "/workspace")).strip(),
        memory=_opt_str(data.get("memory")),
        cpus=_opt_str(data.get("cpus")),
        read_only_mounts=_str_tuple(data.get("read_only_mounts")),
    )


def _coerce_judge_stages(items: Any) -> tuple[JudgeStageConfig, ...]:
    if not items:
        return ()
    if not isinstance(items, list):
        raise ConfigError("evolve.judge.stages must be a list")
    stages: List[JudgeStageConfig] = []
    for item in items:
        if not isinstance(item, dict):
            raise ConfigError("evolve.judge.stages entries must be mappings")
        provides_raw = item.get("provides", [])
        stages.append(
            JudgeStageConfig(
                name=str(item.get("name", "")).strip(),
                command=str(item.get("command", "")).strip(),
                timeout_sec=int(item.get("timeout_sec", 600)),
                parse=_coerce_enum(
                    item.get("parse", JudgeParseMode.EXIT_CODE.value),
                    JudgeParseMode,
                    "evolve.judge stage parse",
                ),
                provides=tuple(str(x).strip() for x in list(provides_raw or [])),
            )
        )
    return tuple(stages)


def _str_tuple(items: Any) -> tuple[str, ...]:
    if not items:
        return ()
    if isinstance(items, (str, bytes)):
        # `list("bench.py")` is eight one-character entries, every one of which passes
        # each per-entry check -- silently protecting nothing at all.
        raise ConfigError(f"expected a list of strings, got a single value: {items!r}")
    return tuple(str(x).strip() for x in list(items))


def _coerce_evolve(evolve: Dict[str, Any]) -> EvolveConfig:
    variation = dict(evolve.get("variation", {}) or {})
    judge = dict(evolve.get("judge", {}) or {})
    supervisor = dict(evolve.get("supervisor", {}) or {})
    stop = dict(evolve.get("stop", {}) or {})
    worker_budget = dict(evolve.get("worker_budget", {}) or {})
    cost_raw = stop.get("max_total_cost_usd")
    turns_raw = worker_budget.get("max_turns")
    return EvolveConfig(
        repo_path=str(evolve.get("repo_path", ".")).strip() or ".",
        seed_ref=str(evolve.get("seed_ref", "HEAD")).strip() or "HEAD",
        run_branch_prefix=str(evolve.get("run_branch_prefix", "evolve/")),
        variation=EvolveVariationConfig(
            kind=_coerce_variation_kind(
                variation.get("kind", VariationKind.SINGLE_AGENT)
            ),
            agent_id=_opt_str(variation.get("agent_id")),
            debate_rounds=int(variation.get("debate_rounds", 2)),
            debate_agent_ids=_str_tuple(variation.get("debate_agent_ids")),
        ),
        judge=JudgeConfig(
            stages=_coerce_judge_stages(judge.get("stages")),
            gate=_coerce_gate_predicates(judge.get("gate"), "judge.gate"),
            comparator=_coerce_comparator(judge.get("comparator")),
            protected_paths=_str_tuple(judge.get("protected_paths")),
            network=bool(judge.get("network", False)),
            container=_coerce_container(judge.get("container")),
            env_passthrough=_str_tuple(judge.get("env_passthrough")),
        ),
        supervisor=EvolveSupervisorConfig(
            stall_window=int(supervisor.get("stall_window", 8)),
            loop_threshold=int(supervisor.get("loop_threshold", 3)),
            directions_ttl_iterations=int(
                supervisor.get("directions_ttl_iterations", 4)
            ),
            max_interventions_before_human=int(
                supervisor.get("max_interventions_before_human", 3)
            ),
            intervention=_coerce_enum(
                supervisor.get("intervention", SupervisorIntervention.DEBATE.value),
                SupervisorIntervention,
                "evolve.supervisor.intervention",
            ),
        ),
        stop=EvolveStopConfig(
            max_iterations=int(stop.get("max_iterations", 40)),
            max_wall_clock_minutes=int(stop.get("max_wall_clock_minutes", 480)),
            max_total_cost_usd=(float(cost_raw) if cost_raw is not None else None),
            target=_coerce_gate_predicates(stop.get("target"), "stop.target"),
        ),
        store_path=str(evolve.get("store_path", ".freemad/evolve/evolve.db")),
        context_budget_chars=int(evolve.get("context_budget_chars", 8000)),
        worker_budget=EvolveWorkerBudgetConfig(
            max_minutes=int(worker_budget.get("max_minutes", 20)),
            max_turns=(int(turns_raw) if turns_raw is not None else None),
        ),
        knowledge_paths=_str_tuple(evolve.get("knowledge_paths")),
    )


def _coerce(cfg_dict: Dict[str, Any]) -> Config:
    agents_list = cfg_dict.get("agents")
    if not agents_list:
        agents = default_agents()
    else:
        if not isinstance(agents_list, list):
            raise ConfigError("config.agents must be a list")
        agents = [_coerce_agent(a) for a in agents_list]

    topology = cfg_dict.get("topology", {})
    deadlines = cfg_dict.get("deadlines", {})
    scoring = cfg_dict.get("scoring", {})
    security = cfg_dict.get("security", {})
    budget = cfg_dict.get("budget", {})
    output = cfg_dict.get("output", {})
    logging = cfg_dict.get("logging", {})
    validation = cfg_dict.get("validation", {})
    cache = cfg_dict.get("cache", {})
    task = cfg_dict.get("task", {})
    task_tool_policy = dict(task.get("tool_policy", {}) or {})

    cfg = Config(
        agents=agents,
        topology=TopologyConfig(
            type=topology.get("type", "all_to_all"),
            k=topology.get("k"),
            seed=int(topology.get("seed", 12345)),
            hub_agent=topology.get("hub_agent"),
        ),
        deadlines=DeadlinesConfig(
            soft_timeout_ms=int(deadlines.get("soft_timeout_ms", 15000)),
            hard_timeout_ms=int(deadlines.get("hard_timeout_ms", 30000)),
            min_agents=int(deadlines.get("min_agents", 2)),
        ),
        scoring=ScoringConfig(
            weights=[float(x) for x in scoring.get("weights", [20, 25, 30, 20])],
            normalize=bool(scoring.get("normalize", True)),
            tie_break=_coerce_tiebreak(
                scoring.get("tie_break", TieBreak.DETERMINISTIC)
            ),
            random_seed=int(scoring.get("random_seed", 987654321)),
        ),
        security=SecurityConfig(
            redact_patterns=list(
                security.get("redact_patterns", SecurityConfig().redact_patterns)
            ),
            max_requirement_size=int(security.get("max_requirement_size", 20000)),
            max_solution_size=int(security.get("max_solution_size", 40000)),
            max_critique_size=int(security.get("max_critique_size", 20000)),
            cli_use_shell=bool(security.get("cli_use_shell", False)),
            cli_timeout_ms=int(security.get("cli_timeout_ms", 60000)),
            cli_allowed_commands=list(
                security.get(
                    "cli_allowed_commands", SecurityConfig().cli_allowed_commands
                )
            ),
        ),
        budget=BudgetConfig(
            max_total_time_sec=_opt_float(budget.get("max_total_time_sec", 120.0)),
            max_round_time_sec=_opt_float(budget.get("max_round_time_sec", 30.0)),
            max_agent_time_sec=_opt_float(budget.get("max_agent_time_sec", 20.0)),
            max_tokens_per_agent_per_round=_opt_int(
                budget.get("max_tokens_per_agent_per_round")
            ),
            max_total_tokens=_opt_int(budget.get("max_total_tokens")),
            enforce_total_tokens=bool(budget.get("enforce_total_tokens", False)),
            enable_token_truncation=bool(budget.get("enable_token_truncation", True)),
            max_concurrent_agents=_opt_int(budget.get("max_concurrent_agents")),
        ),
        output=OutputConfig(
            save_transcript=bool(output.get("save_transcript", True)),
            transcript_dir=str(output.get("transcript_dir", "transcripts")),
            format=output.get("format", "json"),
            verbose=bool(output.get("verbose", False)),
            include_topology_info=bool(output.get("include_topology_info", True)),
        ),
        logging=LoggingConfig(
            level=output_or(logging, "level", "INFO"),
            file=_opt_str(logging.get("file")),
            console=bool(logging.get("console", True)),
            structured=bool(logging.get("structured", False)),
        ),
        validation=ValidationConfig(
            enable_sandbox=bool(validation.get("enable_sandbox", False)),
            sandbox_timeout_ms=int(validation.get("sandbox_timeout_ms", 500)),
        ),
        cache=CacheConfig(
            enabled=bool(cache.get("enabled", False)),
            dir=str(cache.get("dir", ".mad_cache")),
            max_entries=_opt_int(cache.get("max_entries")),
        ),
        task=TaskConfig(
            store_path=str(task.get("store_path", TaskConfig().store_path)),
            artifacts_dir=str(task.get("artifacts_dir", TaskConfig().artifacts_dir)),
            max_stage_retries=int(
                task.get("max_stage_retries", TaskConfig().max_stage_retries)
            ),
            max_total_iterations=int(
                task.get("max_total_iterations", TaskConfig().max_total_iterations)
            ),
            tool_policy=TaskToolPolicyConfig(
                allow_web_research=bool(
                    task_tool_policy.get("allow_web_research", True)
                ),
                allow_workspace_write=bool(
                    task_tool_policy.get("allow_workspace_write", True)
                ),
                allow_local_commands=bool(
                    task_tool_policy.get("allow_local_commands", True)
                ),
                allowed_write_roots=list(
                    task_tool_policy.get("allowed_write_roots", ["."])
                ),
                allowed_local_commands=list(
                    task_tool_policy.get(
                        "allowed_local_commands",
                        TaskToolPolicyConfig().allowed_local_commands,
                    )
                ),
                verification_commands=list(
                    task_tool_policy.get("verification_commands", [])
                ),
            ),
        ),
        evolve=_coerce_evolve(dict(cfg_dict.get("evolve", {}) or {})),
    )
    return cfg


def load_config(
    path: Optional[str | os.PathLike[str]] = None,
    overrides: Optional[Dict[str, Any]] = None,
) -> Config:
    """Load, merge, validate, and finalize a Config.

    - Defaults for 2 agents (Claude/Codex)
    - Optional file (YAML or JSON). If YAML, requires PyYAML
    - Optional overrides dict (deep-merged)
    - Validates and ensures transcript directory if needed
    - Returns an immutable Config
    """
    base_dict: Dict[str, Any] = to_dict(default_config())
    config_root = Path.cwd().resolve()
    if path:
        cfg_file = _resolve_existing_config_file(path)
        config_root = cfg_file.parent
        file_dict = _load_config_file(cfg_file)
        base_dict = _deep_update(base_dict, file_dict)

    if overrides:
        base_dict = _deep_update(base_dict, overrides)

    cfg = _coerce(base_dict)
    cfg = _resolve_evolve_paths(cfg, config_root)
    validate_config(cfg)

    # output.transcript_dir and cache.dir are *used* relative to the working directory
    # (cli.py / DiskCache), so they are created and confined there too. Checking them
    # against the config file's directory created a phantom directory beside the config
    # and rejected overrides that the write path would have accepted.
    working_root = Path.cwd().resolve()
    if cfg.output.save_transcript:
        _ensure_dir(cfg.output.transcript_dir, working_root)
    if cfg.cache.enabled and cfg.cache.dir:
        _ensure_dir(cfg.cache.dir, working_root)

    return cfg


def _resolve_evolve_paths(cfg: Config, root: Path) -> Config:
    """Anchor `evolve.repo_path` and `store_path` to the config file's directory.

    Unlike `output.transcript_dir` and `cache.dir`, which are outputs written relative
    to the working directory, these two name the *input*. Leaving them relative to the
    working directory means `--config
    examples/evolve_toy/evolve.yaml`, run from the repo root exactly as the README
    shows, silently optimizes the outer repository instead.
    """

    def _anchor(value: str) -> str:
        path = Path(value)
        return str(path if path.is_absolute() else (root / path).resolve())

    evolve = cfg.evolve
    return replace(
        cfg,
        evolve=replace(
            evolve,
            repo_path=_anchor(evolve.repo_path),
            store_path=_anchor(evolve.store_path),
        ),
    )


def _ensure_dir(path_str: str, root: Path) -> None:
    p = _resolve_path_under_root(path_str, root, "config-managed directory")
    try:
        # codeql[py/path-injection] `p` is normalized and constrained to the trusted config root.
        p.mkdir(parents=True, exist_ok=True)
    except Exception as e:  # pragma: no cover - defensive
        raise ConfigError(f"failed to create directory {p}: {e}") from e


def _resolve_existing_config_file(path_str: str | os.PathLike[str]) -> Path:
    cfg_file = _resolve_config_file_path(path_str)

    # codeql[py/path-injection] `cfg_file` is normalized and extension-restricted in `_resolve_config_file_path`.
    if not cfg_file.exists():
        raise ConfigError(f"config file does not exist: {cfg_file}")
    # codeql[py/path-injection] `cfg_file` is normalized and extension-restricted in `_resolve_config_file_path`.
    if not cfg_file.is_file():
        raise ConfigError(f"config path must point to a file: {cfg_file}")
    return cfg_file


def _resolve_config_file_path(path_str: str | os.PathLike[str]) -> Path:
    raw = Path(path_str)
    # codeql[py/path-injection] the resolved path is validated before any file access occurs.
    resolved = (
        raw.resolve() if raw.is_absolute() else (Path.cwd().resolve() / raw).resolve()
    )
    if resolved.suffix.lower() not in {".json", ".yaml", ".yml"}:
        raise ConfigError(
            f"config path must point to a .json, .yaml, or .yml file: {resolved}"
        )
    return resolved


def _resolve_path_under_root(
    path_str: str | os.PathLike[str], root: Path, label: str
) -> Path:
    raw = Path(path_str)

    # codeql[py/path-injection] the resolved path is checked to remain under `root` before use.
    resolved = raw.resolve() if raw.is_absolute() else (root.resolve() / raw).resolve()
    # codeql[py/path-injection] `root` is a trusted base directory derived from the config location.
    trusted_root = root.resolve()
    if resolved != trusted_root and trusted_root not in resolved.parents:
        raise ConfigError(f"{label} must stay within {trusted_root}")
    return resolved
