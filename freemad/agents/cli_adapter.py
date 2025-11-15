from __future__ import annotations

import logging
import shlex
import subprocess
import time
from typing import Any, List, Optional, Tuple
import json

from freemad.config import AgentConfig, Config, ConfigError
from freemad.prompts import build_generation_prompt, build_critique_prompt
from freemad.types import Decision, LogEvent
from freemad.utils import parse_generation, parse_critique, compute_answer_id
from freemad.utils.budget import enforce_size, truncate_to_tokens, approx_tokens
from freemad.utils.logger import log_event
from freemad.utils.cache import DiskCache

from .base import Agent, AgentResponse, CritiqueResponse, Metadata


class CLIAdapter(Agent):
    """Generic CLI adapter for Zen MCP-like agents.

    Subclasses can adjust behavior by overriding `_extra_args_generate` or
    `_extra_args_critique` to pass agent-specific CLI subcommands.
    """

    def __init__(self, cfg: Config, agent_cfg: AgentConfig):
        super().__init__(cfg, agent_cfg)
        # lazy logger binding for truncation/caching events
        self.logger: Optional[Any] = None
        try:
            from freemad.utils.logger import get_logger

            self.logger = get_logger(cfg)
        except Exception:  # pragma: no cover
            pass
        self._cache = DiskCache(cfg.cache.dir, cfg.cache.max_entries) if cfg.cache.enabled else None

    def _ensure_allowed(self, exe: str) -> None:
        if exe not in (self.cfg.security.cli_allowed_commands or []):
            raise ConfigError(f"cli command '{exe}' not in allowlist")

    def _run_cli(self, input_text: str, mode: str) -> Tuple[str, float, bool]:
        if not self.agent_cfg.cli_command:
            raise ConfigError(f"agent {self.agent_cfg.id} missing cli_command")
        cmd = shlex.split(self.agent_cfg.cli_command)
        # Insert mode as first positional argument if supported
        # Map internal mode names to CLI-friendly names
        mode_arg = "generate" if mode == "generating" else mode
        if self.agent_cfg.cli_mode_arg:
            cmd.append(mode_arg)
        # 1) single flags (order preserved)
        if self.agent_cfg.cli_flags:
            cmd.extend(list(self.agent_cfg.cli_flags))
        # 2) key=value style flags (sorted for determinism)
        # Append deterministic key-value args as CLI flags
        if self.agent_cfg.cli_args:
            for k in sorted(self.agent_cfg.cli_args.keys()):
                flag = k if k.startswith('-') else f"--{k}"
                cmd.extend([flag, str(self.agent_cfg.cli_args[k])])
        # 3) positional args (order preserved), e.g., ['-']
        if self.agent_cfg.cli_positional:
            cmd.extend(list(self.agent_cfg.cli_positional))
        self._ensure_allowed(cmd[0])
        timeout_s = max(
            self.agent_cfg.timeout or 60.0,
            self.cfg.security.cli_timeout_ms / 1000.0,
            self.cfg.budget.max_agent_time_sec or 10**9,
        )
        # cache lookup
        key = None
        if self._cache is not None:
            cache_meta = {
                "flags": list(self.agent_cfg.cli_flags or []),
                "args": sorted((self.agent_cfg.cli_args or {}).items()),
                "pos": list(self.agent_cfg.cli_positional or []),
            }
            cache_prompt = f"ARGS={json.dumps(cache_meta, sort_keys=True)}\n{input_text}"
            key = self._cache.make_key(mode, self.agent_cfg.id, cache_prompt, self.__class__.__name__, self.agent_cfg.config.temperature, self.agent_cfg.config.max_tokens)
            hit = self._cache.get(key)
            if hit is not None:
                return hit, 0.0, True
        t0 = time.perf_counter()
        if self.logger:
            log_event(self.logger, LogEvent.COMMAND, cmd=cmd, timeout=timeout_s, agent=self.agent_cfg.id, mode=mode)
        proc = subprocess.run(
            cmd,
            input=input_text,
            text=True,
            capture_output=True,
            timeout=timeout_s,
            check=False
        )
        elapsed_ms = (time.perf_counter() - t0) * 1000
        out = (proc.stdout or proc.stderr or "").strip()
        if self.logger:
            log_event(self.logger, LogEvent.COMMAND, level=logging.DEBUG, cmd=cmd, timeout=timeout_s, agent=self.agent_cfg.id, mode=mode, output=out)
        # store in cache
        if self._cache is not None:
            try:
                self._cache.set(key, out)  # type: ignore[arg-type]
            except Exception:
                pass
        return out, elapsed_ms, False

    # Step 3 parsing behavior: one retry if malformed, then default KEEP
    def generate(self, requirement: str) -> AgentResponse:
        prompt = build_generation_prompt(requirement)
        # token budget enforcement for prompt
        if self.cfg.budget.enable_token_truncation and self.cfg.budget.max_tokens_per_agent_per_round is not None:
            prompt, _ = truncate_to_tokens(prompt, self.cfg.budget.max_tokens_per_agent_per_round, label="prompt")
        raw, elapsed_ms, cached = self._run_cli(prompt, mode="generating")
        parsed = parse_generation(raw)
        if parsed.needs_retry:
            # retry with clarification
            retry_prompt = prompt + "\n\nPlease output exactly the SOLUTION and REASONING sections."
            raw, elapsed_ms2, _ = self._run_cli(retry_prompt, mode="generating")
            parsed2 = parse_generation(raw)
            if not parsed2.needs_retry:
                parsed = parsed2
                elapsed_ms += elapsed_ms2
        # Default empty if still invalid
        solution = parsed.solution
        solution, truncated = enforce_size(solution, self.cfg.security.max_solution_size, label="solution")
        if truncated and self.logger:
            log_event(self.logger, LogEvent.TRUNCATE, label="solution", agent=self.agent_cfg.id)
        ans_id = compute_answer_id(solution)
        tokens_out = approx_tokens(solution + "\n\n" + parsed.reasoning)
        tokens_in = approx_tokens(prompt)
        return AgentResponse(
            agent_id=self.agent_cfg.id,
            solution=solution,
            reasoning=parsed.reasoning,
            answer_id=ans_id,
            metadata=Metadata(timings={"elapsed_ms": elapsed_ms, "cached": 1.0 if cached else 0.0}, tokens={"prompt": tokens_in, "output": tokens_out}),
        )

    def critique_and_refine(self, requirement: str, own_response: str, peer_responses: List[str]) -> CritiqueResponse:
        prompt = build_critique_prompt(requirement, own_response, peer_responses)
        if self.cfg.budget.enable_token_truncation and self.cfg.budget.max_tokens_per_agent_per_round is not None:
            prompt, _ = truncate_to_tokens(prompt, self.cfg.budget.max_tokens_per_agent_per_round, label="prompt")
        raw, elapsed_ms, cached = self._run_cli(prompt, mode="critique")
        parsed = parse_critique(raw)
        if parsed.needs_retry:
            retry_prompt = prompt + "\n\nPlease output exactly DECISION and REASONING, and if revising, also REVISED_SOLUTION."
            raw, elapsed_ms2, _ = self._run_cli(retry_prompt, mode="critique")
            parsed2 = parse_critique(raw)
            if not parsed2.needs_retry:
                parsed = parsed2
                elapsed_ms += elapsed_ms2
        # If still invalid: default KEEP without changes
        decision = parsed.decision if not parsed.needs_retry else Decision.KEEP
        changed = decision == Decision.REVISE and bool(parsed.solution)
        new_solution = parsed.solution if (changed and parsed.solution) else own_response
        new_solution, truncated = enforce_size(new_solution, self.cfg.security.max_solution_size, label="solution")
        if truncated and self.logger:
            log_event(self.logger, LogEvent.TRUNCATE, label="solution", agent=self.agent_cfg.id)
        ans_id = compute_answer_id(new_solution)
        tokens_out = approx_tokens((parsed.solution or own_response) + "\n\n" + parsed.reasoning)
        tokens_in = approx_tokens(prompt)
        return CritiqueResponse(
            agent_id=self.agent_cfg.id,
            decision=decision,
            changed=changed,
            solution=new_solution,
            reasoning=parsed.reasoning,
            answer_id=ans_id,
            metadata=Metadata(timings={"elapsed_ms": elapsed_ms, "cached": 1.0 if cached else 0.0}, tokens={"prompt": tokens_in, "output": tokens_out}),
        )
