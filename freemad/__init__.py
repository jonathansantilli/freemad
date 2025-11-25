from __future__ import annotations

"""FREE-MAD Orchestrator package (public API re-exports).

This module re-exports commonly used classes/functions so imports like
`from freemad import X` continue to work after the namespace rename.
"""

__version__ = "0.2.0"

# Config
from freemad.config import (
    Config,
    ConfigError,
    load_config,
    AgentConfig,
    AgentRuntimeConfig,
    SecurityConfig,
)

# Types/enums
from freemad.types import (  # noqa: E402
    Decision,
    RoundType,
    ScoreAction,
    TieBreak,
    GenMarker,
    CritMarker,
    ValidatorName,
    LogEvent,
)

# Prompts
from freemad.prompts import build_generation_prompt, build_critique_prompt  # noqa: E402

# Utils
from freemad.utils import (  # noqa: E402
    parse_generation,
    parse_critique,
    canonicalize_solution,
    compute_answer_id,
)
from freemad.utils.budget import (  # noqa: E402
    BudgetGuard,
    BudgetExceeded,
    TokenBudget,
    enforce_size,
    truncate_to_tokens,
    approx_tokens,
)
from freemad.utils.logger import get_logger, log_event  # noqa: E402
from freemad.utils.cache import DiskCache  # noqa: E402

# Security helpers
from freemad.security import Redactor  # noqa: E402
from freemad.security.secrets import get_secret, SecretSpec  # noqa: E402

# Agents
from freemad.agents.base import (  # noqa: E402
    Agent,
    AgentResponse,
    CritiqueResponse,
    Metadata,
)
from freemad.agents.factory import AgentFactory  # noqa: E402
from freemad.agents.registry import register_agent  # noqa: E402
from freemad.agents import bootstrap  # noqa: E402
from freemad.agents.cli_adapter import CLIAdapter  # noqa: E402

# Topology / Scoring / Orchestrator
from freemad.topology import build_topology  # noqa: E402
from freemad.scoring import ScoreTracker  # noqa: E402
from freemad.orchestrator import Orchestrator  # noqa: E402
from freemad.run_events import RunEvent, RunObserver, NullObserver, FanOutObserver  # noqa: E402
from freemad.types import RunEventKind  # noqa: E402

# Validation
from freemad.validation import ValidationManager  # noqa: E402
from freemad.validation.sandbox import SandboxValidator  # noqa: E402

# CLI / Dashboard public entrypoints
from freemad.cli import main  # noqa: E402
from freemad.dashboard.app import create_app, DashboardConfig  # noqa: E402

__all__ = [
    "__version__",
    # config
    "Config",
    "ConfigError",
    "load_config",
    "AgentConfig",
    "AgentRuntimeConfig",
    "SecurityConfig",
    # enums
    "Decision",
    "RoundType",
    "ScoreAction",
    "TieBreak",
    "GenMarker",
    "CritMarker",
    "ValidatorName",
    "LogEvent",
    "RunEventKind",
    # prompts
    "build_generation_prompt",
    "build_critique_prompt",
    # utils
    "parse_generation",
    "parse_critique",
    "canonicalize_solution",
    "compute_answer_id",
    "BudgetGuard",
    "BudgetExceeded",
    "TokenBudget",
    "enforce_size",
    "truncate_to_tokens",
    "approx_tokens",
    "get_logger",
    "log_event",
    "DiskCache",
    # security
    "Redactor",
    "get_secret",
    "SecretSpec",
    # agents
    "Agent",
    "AgentResponse",
    "CritiqueResponse",
    "Metadata",
    "AgentFactory",
    "register_agent",
    "bootstrap",
    "CLIAdapter",
    # topology/scoring/orchestrator
    "build_topology",
    "ScoreTracker",
    "Orchestrator",
    "RunEvent",
    "RunEventKind",
    "RunObserver",
    "NullObserver",
    "FanOutObserver",
    # validation
    "ValidationManager",
    "SandboxValidator",
    # cli/dashboard
    "main",
    "create_app",
    "DashboardConfig",
]
