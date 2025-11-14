from __future__ import annotations

import dataclasses
import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional
from freemad.types import TieBreak


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
    # Extra CLI key-value arguments appended to the command as flags.
    # Each entry (k: v) becomes either ['--k', 'v'] or [k, 'v'] if k already starts with '-'.
    cli_args: Dict[str, str] = field(default_factory=dict)
    # Extra single flags appended verbatim (order preserved), e.g., ['--enable', '-v']
    cli_flags: List[str] = field(default_factory=list)
    # Extra positional args appended at the very end (order preserved), e.g., ['-']
    cli_positional: List[str] = field(default_factory=list)


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
    api_key_source: Optional[str] = None
    api_key_name: Optional[str] = None
    redact_patterns: List[str] = field(
        default_factory=lambda: [r"sk-[A-Za-z0-9_\-]+", r"(?i)api[_-]?key\s*[:=]\s*\S+"]
    )
    max_requirement_size: int = 20000  # bytes/characters
    max_solution_size: int = 40000
    max_critique_size: int = 20000
    cli_use_shell: bool = False
    cli_timeout_ms: int = 60000
    cli_allowed_commands: List[str] = field(
        default_factory=lambda: [
            # Keep intentionally strict; adapters can override via config
            "zen", "zen-mcp", "claude", "codex",
        ]
    )


@dataclass(frozen=True)
class BudgetConfig:
    max_total_time_sec: Optional[float] = 120.0
    max_round_time_sec: Optional[float] = 30.0
    max_agent_time_sec: Optional[float] = 20.0
    max_tokens_per_agent_per_round: Optional[int] = None
    max_total_tokens: Optional[int] = None
    enforce_total_tokens: bool = False  # when True, exceeding raises; default = log only
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
        return {k: _asdict_cfg(v) for k, v in dataclasses.asdict(cfg).items()}
    if isinstance(cfg, list):
        return [_asdict_cfg(x) for x in cfg]
    return cfg


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
    except ModuleNotFoundError as e:
        raise ConfigError(
            "PyYAML is not installed; provide JSON config or install pyyaml"
        ) from e


def _load_config_file(path: Path) -> Dict[str, Any]:
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
        cli_command=(str(obj["cli_command"]).strip() if obj.get("cli_command") else None),
        timeout=float(obj.get("timeout", 60.0)),
        config=AgentRuntimeConfig(
            temperature=float(obj.get("config", {}).get("temperature", 0.7)),
            max_tokens=(
                int(obj.get("config", {}).get("max_tokens"))
                if obj.get("config", {}).get("max_tokens") is not None
                else None
            ),
        ),
        cli_args={str(k): str(v) for k, v in dict(obj.get("cli_args", {}) or {}).items()},
        cli_flags=[str(x) for x in list(obj.get("cli_flags", []) or [])],
        cli_positional=[str(x) for x in list(obj.get("cli_positional", []) or [])],
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
            tie_break=_coerce_tiebreak(scoring.get("tie_break", TieBreak.DETERMINISTIC)),
            random_seed=int(scoring.get("random_seed", 987654321)),
        ),
        security=SecurityConfig(
            api_key_source=security.get("api_key_source"),
            api_key_name=security.get("api_key_name"),
            redact_patterns=list(security.get("redact_patterns", SecurityConfig().redact_patterns)),
            max_requirement_size=int(security.get("max_requirement_size", 20000)),
            max_solution_size=int(security.get("max_solution_size", 40000)),
            max_critique_size=int(security.get("max_critique_size", 20000)),
            cli_use_shell=bool(security.get("cli_use_shell", False)),
            cli_timeout_ms=int(security.get("cli_timeout_ms", 60000)),
            cli_allowed_commands=list(security.get("cli_allowed_commands", SecurityConfig().cli_allowed_commands)),
        ),
        budget=BudgetConfig(
            max_total_time_sec=_opt_float(budget.get("max_total_time_sec", 120.0)),
            max_round_time_sec=_opt_float(budget.get("max_round_time_sec", 30.0)),
            max_agent_time_sec=_opt_float(budget.get("max_agent_time_sec", 20.0)),
            max_tokens_per_agent_per_round=_opt_int(budget.get("max_tokens_per_agent_per_round")),
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
    if path:
        cfg_file = Path(path)
        if not cfg_file.exists():
            raise ConfigError(f"config file does not exist: {cfg_file}")
        file_dict = _load_config_file(cfg_file)
        base_dict = _deep_update(base_dict, file_dict)

    if overrides:
        base_dict = _deep_update(base_dict, overrides)

    cfg = _coerce(base_dict)
    validate_config(cfg)

    # Ensure transcript dir exists if requested
    if cfg.output.save_transcript:
        _ensure_dir(cfg.output.transcript_dir)
    # Ensure cache dir if enabled
    if cfg.cache.enabled and cfg.cache.dir:
        _ensure_dir(cfg.cache.dir)

    return cfg


def _ensure_dir(path_str: str) -> None:
    p = Path(path_str)
    try:
        p.mkdir(parents=True, exist_ok=True)
    except Exception as e:  # pragma: no cover - defensive
        raise ConfigError(f"failed to create directory {p}: {e}") from e
