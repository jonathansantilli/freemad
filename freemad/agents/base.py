from __future__ import annotations

import abc
import shlex
import shutil
import subprocess
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from freemad import AgentConfig, Config
from freemad import Decision


@dataclass(frozen=True)
class Metadata:
    timings: Dict[str, float] = field(default_factory=dict)  # ms
    tokens: Dict[str, int] = field(default_factory=dict)


@dataclass(frozen=True)
class AgentResponse:
    agent_id: str
    solution: str
    reasoning: str
    answer_id: Optional[str]
    metadata: Metadata = field(default_factory=Metadata)


@dataclass(frozen=True)
class CritiqueResponse:
    agent_id: str
    decision: Decision
    changed: bool
    solution: str
    reasoning: str
    answer_id: Optional[str]
    metadata: Metadata = field(default_factory=Metadata)


@dataclass(frozen=True)
class HealthStatus:
    agent_id: str
    available: bool
    message: str = ""
    version: Optional[str] = None
    command: Optional[str] = None
    latency_ms: Optional[float] = None


class Agent(abc.ABC):
    """Abstract agent interface. Adapters must implement the two calls.

    Implementations should be deterministic under fixed prompts and seeds.
    """

    def __init__(self, cfg: Config, agent_cfg: AgentConfig):
        self.cfg = cfg
        self.agent_cfg = agent_cfg

    @abc.abstractmethod
    def generate(self, requirement: str) -> AgentResponse:
        ...

    @abc.abstractmethod
    def critique_and_refine(
        self, requirement: str, own_response: str, peer_responses: List[str]
    ) -> CritiqueResponse:
        ...

    def health(self) -> HealthStatus:
        """Default health check: verify cli_command exists and responds to --version.

        Adapters may override for richer checks.
        """
        cmd = self.agent_cfg.cli_command
        if not cmd:
            return HealthStatus(
                agent_id=self.agent_cfg.id,
                available=False,
                message="cli_command not configured",
            )

        try:
            parts = shlex.split(cmd)
        except ValueError:
            return HealthStatus(
                agent_id=self.agent_cfg.id,
                available=False,
                message="invalid cli_command string",
                command=cmd,
            )

        exe = parts[0]
        if not self._is_allowed_command(exe):
            return HealthStatus(
                agent_id=self.agent_cfg.id,
                available=False,
                message=f"command '{exe}' not in allowlist",
                command=exe,
            )

        if shutil.which(exe) is None:
            return HealthStatus(
                agent_id=self.agent_cfg.id,
                available=False,
                message=f"command '{exe}' not found on PATH",
                command=exe,
            )

        # Try a lightweight version check
        t0 = time.perf_counter()
        try:
            proc = subprocess.run(
                [exe, "--version"],
                check=False,
                capture_output=True,
                text=True,
                timeout=self.cfg.security.cli_timeout_ms / 1000.0,
            )
            latency_ms = (time.perf_counter() - t0) * 1000
            out = (proc.stdout or proc.stderr or "").strip()
            if proc.returncode == 0 or out:
                return HealthStatus(
                    agent_id=self.agent_cfg.id,
                    available=True,
                    message="ok",
                    version=out.splitlines()[0] if out else None,
                    command=exe,
                    latency_ms=latency_ms,
                )
            return HealthStatus(
                agent_id=self.agent_cfg.id,
                available=False,
                message="no version output",
                command=exe,
                latency_ms=latency_ms,
            )
        except subprocess.TimeoutExpired:
            return HealthStatus(
                agent_id=self.agent_cfg.id,
                available=False,
                message="version check timed out",
                command=exe,
            )
        except Exception as e:  # pragma: no cover - defensive
            return HealthStatus(
                agent_id=self.agent_cfg.id,
                available=False,
                message=f"health error: {e}",
                command=exe,
            )

    def _is_allowed_command(self, exe: str) -> bool:
        return exe in (self.cfg.security.cli_allowed_commands or [])
