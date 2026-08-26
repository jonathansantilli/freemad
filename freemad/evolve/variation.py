from __future__ import annotations

import os
import shlex
import subprocess
import time
from dataclasses import dataclass, replace
from pathlib import Path
from typing import List, Optional, Protocol, Sequence, Tuple

from freemad.agents.base import Agent
from freemad.config import Config, ConfigError
from freemad.evolve.container import (
    build_argv,
    container_name,
    kill_container,
    require_runtime,
)
from freemad.evolve.sandbox import scrubbed_env
from freemad.prompts.evolve import (
    build_debate_requirement,
    build_implementation_mandate,
    build_worker_requirement,
    extract_self_report,
)
from freemad.tasks.models import FileWrite, TaskRequest
from freemad.types import ActionKind, ArtifactKind, TaskRole, TaskStage, VariationKind
from freemad.utils.budget import enforce_size

SELF_REPORT_MAX_CHARS = 2200
FINAL_OUTPUT_MAX_CHARS = 4000


class VariationPolicyError(RuntimeError):
    """A worker's proposed writes or commands violated policy.

    Distinct from `ConfigError`, which stays fatal: a bad *config* is the operator's
    problem and should stop the run, but a bad *proposal* is just a failed iteration.
    A worker must not be able to end the whole optimization with one stray path.
    """


def _remaining_budget(cfg: Config, started: float) -> float:
    """What is left of this iteration's `worker_budget` after the agent call."""
    total = float(cfg.evolve.worker_budget.max_minutes) * 60.0
    return max(0.0, total - (time.perf_counter() - started))


def scope_worker_budget(cfg: Config) -> Config:
    """Cap every worker-facing timeout at `evolve.worker_budget.max_minutes`.

    `evolve.md` section 2.2: the outer budget always wins. The CLI adapter takes the
    *max* of the agent timeout and `security.cli_timeout_ms`, so both have to come down
    for the cap to bind. Judge stage timeouts are deliberately untouched -- the judge is
    not the worker.
    """
    budget_sec = float(cfg.evolve.worker_budget.max_minutes) * 60.0
    agents = [
        replace(a, timeout=min(a.timeout or budget_sec, budget_sec)) for a in cfg.agents
    ]
    security = replace(
        cfg.security,
        cli_timeout_ms=int(min(cfg.security.cli_timeout_ms, budget_sec * 1000)),
    )
    return replace(cfg, agents=agents, security=security)


def scope_debate_agents(cfg: Config) -> Config:
    """Restrict a debate to `evolve.variation.debate_agent_ids`; empty means all of them."""
    wanted = cfg.evolve.variation.debate_agent_ids
    if not wanted:
        return cfg
    chosen = [a for a in cfg.agents if a.id in wanted]
    return replace(cfg, agents=chosen)


def scope_debate_budget(cfg: Config, elapsed_sec: float) -> Config:
    """Scope an inner debate's total-time guard to what is left of the iteration."""
    budget_sec = float(cfg.evolve.worker_budget.max_minutes) * 60.0
    remaining = max(1.0, budget_sec - elapsed_sec)
    current = cfg.budget.max_total_time_sec
    scoped = remaining if current is None else min(current, remaining)
    return replace(cfg, budget=replace(cfg.budget, max_total_time_sec=scoped))


def require_launchable(agent: Agent) -> None:
    """Fail at run creation, not silently on every iteration.

    A CLI-backed agent with no `cli_command`, or one whose executable
    `security.cli_allowed_commands` refuses, raises inside `act()` — which the operator
    turns into a `WORKER_FAILED` outcome. The run then spends its entire iteration budget
    doing nothing and stops cleanly, with no crash and no obvious symptom. Three shipped
    example configs did exactly that, and `evolve validate` could not see it because it
    exercises the judge and never the agent.
    """
    from freemad.agents.cli_adapter import CLIAdapter

    if not isinstance(agent, CLIAdapter):
        return
    command = agent.agent_cfg.cli_command
    if not command or not command.strip():
        raise ConfigError(
            f"agent '{agent.agent_cfg.id}' has no cli_command, so it cannot be launched"
        )
    executable = shlex.split(command)[0]
    allowed = agent.cfg.security.cli_allowed_commands or []
    if executable not in allowed:
        raise ConfigError(
            f"agent '{agent.agent_cfg.id}' runs '{executable}', which "
            f"security.cli_allowed_commands refuses: {allowed}"
        )


def require_act_capability(agent: Agent) -> None:
    """Fail fast when an adapter does not implement autonomous actions."""
    if type(agent).act is Agent.act:
        raise ConfigError(
            f"agent '{agent.agent_cfg.id}' does not implement act(); "
            f"it cannot serve as a single-agent variation operator"
        )


class VariationOperator(Protocol):
    def propose(
        self,
        context_doc: str,
        worktree: Path,
        directives: Tuple[str, ...],
        agent: Optional[Agent] = None,
        run_id: str = "",
        iteration: int = 0,
        goal: str = "",
    ) -> "VariationOutcome": ...


@dataclass(frozen=True)
class VariationOutcome:
    result_changed_files: bool
    self_report: str
    final_output: str
    worker_error: Optional[str]
    commands_run: Tuple[str, ...] = ()
    writes_applied: int = 0
    duration_ms: int = 0
    transcript_ref: Optional[str] = None
    agent_ids: Tuple[str, ...] = ()


def _under_any_root(target: Path, workspace_root: Path, roots: Sequence[str]) -> bool:
    """Mirrors `TaskOrchestrator._is_under_roots`."""
    for raw in roots:
        candidate = Path(raw)
        base = (
            candidate.resolve()
            if candidate.is_absolute()
            else (workspace_root / candidate).resolve()
        )
        if target == base or base in target.parents:
            return True
    return False


def apply_writes_policy(cfg: Config, writes: Tuple[FileWrite, ...], root: Path) -> int:
    """Policy-bound file writes inside the worktree (mirrors tasks runtime)."""
    if not writes:
        return 0
    policy = cfg.task.tool_policy
    if not policy.allow_workspace_write:
        raise ConfigError("task tool policy forbids workspace writes")
    resolved_root = root.resolve()
    applied = 0
    for write in writes:
        relative_path = Path(write.path)
        if relative_path.is_absolute():
            raise VariationPolicyError("evolve writes must use relative paths")
        target = (resolved_root / relative_path).resolve()
        if target == resolved_root:
            # "." resolves to the worktree root; write_text on it is IsADirectoryError.
            raise VariationPolicyError(
                "evolve writes must name a file, not the worktree root"
            )
        if resolved_root not in target.parents:
            raise VariationPolicyError(f"write path escapes worktree: {write.path}")
        if ".git" in target.relative_to(resolved_root).parts:
            # In a linked worktree `.git` is a *file*, so writing "through" it raises;
            # it is also how a worker would install a hook the commit step then runs.
            raise VariationPolicyError(
                f"evolve writes must not touch .git: {write.path}"
            )
        if not _under_any_root(target, resolved_root, policy.allowed_write_roots):
            # The tasks runtime enforces this; evolve silently ignored it, so narrowing
            # writes to ["src"] was honoured by `freemad task` and dropped by `freemad
            # evolve` against the same config.
            raise VariationPolicyError(
                f"write path outside task.tool_policy.allowed_write_roots: {write.path}"
            )
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(write.content, encoding="utf-8")
        except OSError as exc:
            raise VariationPolicyError(f"write failed for {write.path}: {exc}") from exc
        applied += 1
    return applied


def run_commands_policy(
    cfg: Config,
    commands: Tuple[str, ...],
    root: Path,
    budget_sec: Optional[float] = None,
) -> List[str]:
    """Policy-bound local commands inside the worktree (mirrors tasks runtime).

    `budget_sec` is what is LEFT of the iteration's `worker_budget`, and it is spent
    down across the whole list. Without it each command got the full per-call cap, so N
    worker commands could consume N x the budget that section 2.2 calls the iteration's.
    """
    policy = cfg.task.tool_policy
    if not commands:
        return []
    if not policy.allow_local_commands:
        raise ConfigError("task tool policy forbids local commands")
    judge = cfg.evolve.judge
    env = scrubbed_env(judge.env_passthrough, network=judge.network)
    if judge.container.enabled:
        require_runtime(judge.container)
    per_call = cfg.security.cli_timeout_ms / 1000.0
    remaining = budget_sec
    run: List[str] = []
    for command in commands:
        try:
            cmd = shlex.split(command)
        except ValueError as exc:
            # An unbalanced quote is worker input, not a runtime fault.
            raise VariationPolicyError(
                f"unparseable command {command!r}: {exc}"
            ) from exc
        if not cmd:
            continue
        if cmd[0] not in policy.allowed_local_commands:
            raise VariationPolicyError(
                f"command '{cmd[0]}' not allowed for evolve workers"
            )
        if remaining is not None and remaining <= 0:
            raise VariationPolicyError(
                f"worker budget exhausted before running: {command}"
            )
        timeout = per_call if remaining is None else min(per_call, remaining)
        started_cmd = time.perf_counter()
        name: Optional[str] = None
        if judge.container.enabled:
            name = container_name("freemad-worker")
            argv = build_argv(
                judge.container,
                cmd,
                root,
                env,
                network=judge.network,
                name=name,
                uid_gid=(
                    f"{os.getuid()}:{os.getgid()}" if hasattr(os, "getuid") else None
                ),
            )
            run_kwargs: dict = {}
        else:
            argv = cmd
            run_kwargs = {"cwd": str(root), "env": env}
        try:
            subprocess.run(  # noqa: S603 - fixed argv from allowlisted command
                argv,
                text=True,
                capture_output=True,
                timeout=timeout,
                check=False,
                **run_kwargs,
            )
        except subprocess.TimeoutExpired as exc:
            if name is not None:
                kill_container(judge.container.runtime, name)
            raise VariationPolicyError(f"worker command timed out: {command}") from exc
        except OSError as exc:
            # Missing binary, permission denied, exec format error. `judge.py` already
            # treats this class as a stage failure; it must not be fatal here either.
            raise VariationPolicyError(
                f"worker command could not start: {command}: {exc}"
            ) from exc
        finally:
            if remaining is not None:
                remaining -= time.perf_counter() - started_cmd
        run.append(command)
    return run


def build_worker_request(
    run_id: str, iteration: int, requirement: str, worktree: Path
) -> TaskRequest:
    return TaskRequest(
        task_id=f"{run_id}-it{iteration}",
        goal=requirement,
        stage=TaskStage.EXECUTE,
        role=TaskRole.IMPLEMENTER,
        workspace_root=str(worktree),
        allowed_actions=(ActionKind.WRITE_FILE, ActionKind.RUN_COMMAND),
        required_output_kind=ArtifactKind.PATCH,
    )


def worktree_is_dirty(worktree: Path) -> bool:
    """Untracked files count: the accept path stages them with `git add -A`.

    Excluding them (`-uno`) reports an agent that only *added* files as having done
    nothing, which then lands in the graveyard as "no changes produced".
    """
    proc = subprocess.run(  # noqa: S603 - fixed argv
        ["git", "status", "--porcelain"],
        cwd=str(worktree),
        text=True,
        capture_output=True,
        timeout=30,
        check=False,
    )
    return proc.stdout.strip() != ""


class SingleAgentOperator:
    """One agent proposes changes directly in the worktree under freemad policy."""

    def __init__(self, cfg: Config):
        self._cfg = cfg

    def propose(
        self,
        context_doc: str,
        worktree: Path,
        directives: Tuple[str, ...],
        agent: Optional[Agent] = None,
        run_id: str = "",
        iteration: int = 0,
        goal: str = "",
    ) -> VariationOutcome:
        if agent is None:
            raise ConfigError("single_agent variation requires a resolved worker agent")
        require_act_capability(agent)
        started = time.perf_counter()

        requirement = build_worker_requirement(
            goal,
            context_doc,
            directives,
            self._cfg.evolve.knowledge_paths,
            root=worktree,
        )
        request = build_worker_request(run_id, iteration, requirement, worktree)
        try:
            response = agent.act(request)
        except Exception as exc:  # noqa: BLE001 - worker failure becomes an outcome
            return VariationOutcome(
                result_changed_files=False,
                self_report="",
                final_output="",
                worker_error=enforce_size(str(exc), 1000, "worker_error")[0],
                duration_ms=int((time.perf_counter() - started) * 1000),
            )

        try:
            writes_applied = apply_writes_policy(self._cfg, response.writes, worktree)
            commands_run = run_commands_policy(
                self._cfg,
                response.commands,
                worktree,
                budget_sec=_remaining_budget(self._cfg, started),
            )
        except VariationPolicyError as exc:
            return VariationOutcome(
                result_changed_files=False,
                self_report="",
                final_output=enforce_size(
                    response.content, FINAL_OUTPUT_MAX_CHARS, "final_output"
                )[0],
                worker_error=enforce_size(str(exc), 1000, "worker_error")[0],
                duration_ms=int((time.perf_counter() - started) * 1000),
            )

        changed = writes_applied > 0 or worktree_is_dirty(worktree)
        return VariationOutcome(
            result_changed_files=changed,
            self_report=extract_self_report(response.content, SELF_REPORT_MAX_CHARS),
            final_output=enforce_size(
                response.content, FINAL_OUTPUT_MAX_CHARS, "final_output"
            )[0],
            worker_error=None,
            commands_run=tuple(commands_run),
            writes_applied=writes_applied,
            duration_ms=int((time.perf_counter() - started) * 1000),
        )


class DebateOperator:
    """Two-step variation: a debate selects a plan; its origin agent implements it.

    Never parse patches from debate prose: the winning plan is handed back to
    the origin agent, which must implement exactly that proposal in the
    worktree. Both steps count against the iteration budget.
    """

    def __init__(self, cfg: Config):
        self._cfg = cfg

    def propose(
        self,
        context_doc: str,
        worktree: Path,
        directives: Tuple[str, ...],
        agent: Optional[Agent] = None,
        run_id: str = "",
        iteration: int = 0,
        goal: str = "",
    ) -> VariationOutcome:
        from freemad.agents.factory import AgentFactory
        from freemad.orchestrator import Orchestrator

        started = time.perf_counter()
        requirement = build_debate_requirement(
            goal,
            context_doc,
            directives,
            self._cfg.evolve.knowledge_paths,
            root=worktree,
        )

        try:
            scoped = scope_debate_agents(
                scope_debate_budget(self._cfg, time.perf_counter() - started)
            )
            result = Orchestrator(scoped).run(
                requirement, max_rounds=max(1, self._cfg.evolve.variation.debate_rounds)
            )
        except Exception as exc:  # noqa: BLE001 - debate failure becomes an outcome
            return VariationOutcome(
                result_changed_files=False,
                self_report="",
                final_output="",
                worker_error=enforce_size(
                    f"debate failed: {exc}", 1000, "worker_error"
                )[0],
                duration_ms=int((time.perf_counter() - started) * 1000),
            )

        plan = str(result.get("final_solution", "")).strip()
        transcript_ref = _save_debate_transcript(self._cfg, run_id, iteration, result)

        origin_ids: List[str] = list(result.get("origin_agents") or []) or list(
            result.get("winning_agents") or []
        )
        implementer = agent
        if implementer is None and origin_ids:
            factory = AgentFactory(self._cfg)
            agents = factory.build_all()
            implementer = agents.get(origin_ids[0])
        if implementer is None:
            return VariationOutcome(
                result_changed_files=False,
                self_report="",
                final_output=enforce_size(plan, FINAL_OUTPUT_MAX_CHARS, "final_output")[
                    0
                ],
                worker_error="debate produced no resolvable origin agent to implement",
                transcript_ref=transcript_ref,
                duration_ms=int((time.perf_counter() - started) * 1000),
            )
        try:
            require_act_capability(implementer)
        except ConfigError as exc:
            # Which agent implements is decided by the debate, not by static config,
            # so an incapable winner is a failed iteration rather than a broken setup.
            return VariationOutcome(
                result_changed_files=False,
                self_report="",
                final_output=enforce_size(plan, FINAL_OUTPUT_MAX_CHARS, "final_output")[
                    0
                ],
                worker_error=enforce_size(str(exc), 1000, "worker_error")[0],
                transcript_ref=transcript_ref,
                duration_ms=int((time.perf_counter() - started) * 1000),
            )

        mandate = build_implementation_mandate(plan)
        request = build_worker_request(run_id, iteration, mandate, worktree)
        try:
            response = implementer.act(request)
        except Exception as exc:  # noqa: BLE001 - implementer failure becomes an outcome
            return VariationOutcome(
                result_changed_files=False,
                self_report="",
                final_output=enforce_size(plan, FINAL_OUTPUT_MAX_CHARS, "final_output")[
                    0
                ],
                worker_error=enforce_size(str(exc), 1000, "worker_error")[0],
                transcript_ref=transcript_ref,
                duration_ms=int((time.perf_counter() - started) * 1000),
            )

        try:
            writes_applied = apply_writes_policy(self._cfg, response.writes, worktree)
            commands_run = run_commands_policy(
                self._cfg,
                response.commands,
                worktree,
                budget_sec=_remaining_budget(self._cfg, started),
            )
        except VariationPolicyError as exc:
            return VariationOutcome(
                result_changed_files=False,
                self_report="",
                final_output=enforce_size(plan, FINAL_OUTPUT_MAX_CHARS, "final_output")[
                    0
                ],
                worker_error=enforce_size(str(exc), 1000, "worker_error")[0],
                transcript_ref=transcript_ref,
                duration_ms=int((time.perf_counter() - started) * 1000),
            )
        changed = writes_applied > 0 or worktree_is_dirty(worktree)
        return VariationOutcome(
            result_changed_files=changed,
            self_report=extract_self_report(response.content, SELF_REPORT_MAX_CHARS),
            final_output=enforce_size(plan, FINAL_OUTPUT_MAX_CHARS, "final_output")[0],
            worker_error=None,
            commands_run=tuple(commands_run),
            writes_applied=writes_applied,
            transcript_ref=transcript_ref,
            duration_ms=int((time.perf_counter() - started) * 1000),
            agent_ids=tuple(dict.fromkeys([*origin_ids, implementer.agent_cfg.id])),
        )


def transcript_dir(cfg: Config, run_id: str) -> Path:
    """Beside the store, so all of a run's state lands in one place.

    A bare relative `.freemad/` would follow the *process* working directory, scattering
    transcripts wherever the CLI happened to be invoked from.
    """
    return Path(cfg.evolve.store_path).resolve().parent / "transcripts" / run_id


def _save_debate_transcript(
    cfg: Config, run_id: str, iteration: int, result: dict
) -> Optional[str]:
    import json

    base = transcript_dir(cfg, run_id)
    try:
        base.mkdir(parents=True, exist_ok=True)
        path = base / f"it{iteration}_debate.json"
        path.write_text(
            json.dumps(result.get("transcript", []), default=str), encoding="utf-8"
        )
        return str(path)
    except OSError:
        return None


def make_operator(cfg: Config):
    kind = cfg.evolve.variation.kind
    if kind == VariationKind.DEBATE:
        return DebateOperator(cfg)
    return SingleAgentOperator(cfg)


__all__ = [
    "DebateOperator",
    "transcript_dir",
    "VariationPolicyError",
    "scope_debate_agents",
    "scope_debate_budget",
    "scope_worker_budget",
    "SingleAgentOperator",
    "VariationOperator",
    "VariationOutcome",
    "make_operator",
    "require_act_capability",
    "require_launchable",
    "worktree_is_dirty",
]
