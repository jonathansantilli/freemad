from __future__ import annotations

import argparse
import json
import shlex
import subprocess
import sys
from dataclasses import replace
from pathlib import Path, PurePosixPath
from typing import Any

from freemad.agents import bootstrap as agent_bootstrap
from freemad.config import ConfigError, load_config
from freemad.evolve.judge import Judge, target_met
from freemad.utils.budget import enforce_size
from freemad.evolve.lineage import Lineage, LineageError
from freemad.evolve.orchestrator import EvolveOrchestrator
from freemad.orchestrator import Orchestrator
from freemad.task_events import TaskEvent
from freemad.tasks.orchestrator import TaskOrchestrator
from freemad.types import (
    EvolveRunStatus,
    EvolveStopReason,
    TaskEventKind,
    TaskStatus,
    TaskType,
    VariationKind,
)
from freemad.utils.transcript import save_transcript


PACKAGE_VERSION = "0.1.0"


def _task_payload(orch: TaskOrchestrator, task_id: str) -> dict[str, Any]:
    task = orch.get_task(task_id)
    if task is None:
        raise ConfigError(f"unknown task id: {task_id}")
    return {
        **task.to_dict(),
        "artifacts": [
            artifact.to_dict() for artifact in orch.store.list_artifacts(task_id)
        ],
        "work_items": [item.to_dict() for item in orch.store.list_work_items(task_id)],
        "events": [event.to_dict() for event in orch.store.list_events(task_id)],
    }


def _task_main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="freemad task", description="FREE-MAD autonomous task CLI"
    )
    sub = parser.add_subparsers(dest="task_command", required=True)

    start = sub.add_parser("start", help="Create and run a new autonomous task")
    start.add_argument("goal", help="Task goal")
    start.add_argument("--config", help="Path to config file (yaml/json)")
    start.add_argument(
        "--task-type",
        choices=[TaskType.PLAN.value, TaskType.CODE.value],
        default=TaskType.PLAN.value,
    )
    start.add_argument(
        "--workspace-root",
        default=".",
        help="Workspace root for autonomous task execution",
    )

    resume = sub.add_parser("resume", help="Resume an existing autonomous task")
    resume.add_argument("task_id", help="Task id")
    resume.add_argument("--config", help="Path to config file (yaml/json)")

    inspect = sub.add_parser("inspect", help="Inspect an autonomous task")
    inspect.add_argument("task_id", help="Task id")
    inspect.add_argument("--config", help="Path to config file (yaml/json)")

    status = sub.add_parser("status", help="Show task status")
    status.add_argument("task_id", help="Task id")
    status.add_argument("--config", help="Path to config file (yaml/json)")

    answer = sub.add_parser("answer", help="Record human input for a task")
    answer.add_argument("task_id", help="Task id")
    answer.add_argument("text", help="Human answer")
    answer.add_argument("--config", help="Path to config file (yaml/json)")

    approve = sub.add_parser("approve", help="Record a human approval decision")
    approve.add_argument("task_id", help="Task id")
    approve.add_argument("stage", help="Stage being approved")
    approve.add_argument("--config", help="Path to config file (yaml/json)")

    pause = sub.add_parser("pause", help="Pause an autonomous task")
    pause.add_argument("task_id", help="Task id")
    pause.add_argument("--config", help="Path to config file (yaml/json)")

    args = parser.parse_args(argv)

    try:
        cfg = load_config(path=args.config if getattr(args, "config", None) else None)
    except ConfigError as e:
        print(f"config error: {e}", file=sys.stderr)
        return 2

    orch = TaskOrchestrator(cfg)
    try:
        if args.task_command == "start":
            task = orch.create_task(
                goal=args.goal,
                task_type=TaskType(args.task_type),
                workspace_root=args.workspace_root,
            )
            orch.run(task.task_id)
            print(json.dumps(_task_payload(orch, task.task_id)))
            return 0

        if args.task_command == "resume":
            existing_task = orch.get_task(args.task_id)
            if existing_task is None:
                raise ConfigError(f"unknown task id: {args.task_id}")
            if existing_task.status in {
                TaskStatus.PAUSED,
                TaskStatus.WAITING_FOR_HUMAN,
            }:
                orch.store.update_task(
                    replace(existing_task, status=TaskStatus.RUNNING)
                )
            orch.run(args.task_id)
            print(json.dumps(_task_payload(orch, args.task_id)))
            return 0

        if args.task_command in {"inspect", "status"}:
            print(json.dumps(_task_payload(orch, args.task_id)))
            return 0

        if args.task_command == "answer":
            existing_task = orch.get_task(args.task_id)
            if existing_task is None:
                raise ConfigError(f"unknown task id: {args.task_id}")
            orch.store.append_event(
                TaskEvent(
                    kind=TaskEventKind.HUMAN_INPUT_RECEIVED,
                    task_id=args.task_id,
                    ts_ms=orch._now(),
                    status=existing_task.status,
                    message=args.text,
                )
            )
            print(json.dumps(_task_payload(orch, args.task_id)))
            return 0

        if args.task_command == "approve":
            existing_task = orch.get_task(args.task_id)
            if existing_task is None:
                raise ConfigError(f"unknown task id: {args.task_id}")
            orch.store.append_event(
                TaskEvent(
                    kind=TaskEventKind.DECISION_RECORDED,
                    task_id=args.task_id,
                    ts_ms=orch._now(),
                    status=existing_task.status,
                    message=args.stage,
                )
            )
            print(json.dumps(_task_payload(orch, args.task_id)))
            return 0

        if args.task_command == "pause":
            existing_task = orch.get_task(args.task_id)
            if existing_task is None:
                raise ConfigError(f"unknown task id: {args.task_id}")
            orch.store.update_task(replace(existing_task, status=TaskStatus.PAUSED))
            orch.store.append_event(
                TaskEvent(
                    kind=TaskEventKind.TASK_PAUSED,
                    task_id=args.task_id,
                    ts_ms=orch._now(),
                    status=TaskStatus.PAUSED,
                )
            )
            print(json.dumps(_task_payload(orch, args.task_id)))
            return 0
    except ConfigError as e:
        print(f"task error: {e}", file=sys.stderr)
        return 2
    except Exception as e:
        print(f"task runtime error: {e}", file=sys.stderr)
        return 1
    return 2


def _evolve_main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="freemad evolve", description="FREE-MAD evolve runtime CLI"
    )
    sub = parser.add_subparsers(dest="evolve_command", required=True)

    start = sub.add_parser("start", help="Create and run a new evolve optimization")
    start.add_argument("goal", help="Optimization goal")
    start.add_argument(
        "--config", required=True, help="Path to config file (yaml/json)"
    )

    validate = sub.add_parser(
        "validate", help="Validate config, repo, and judge dry-run on seed"
    )
    validate.add_argument(
        "--config", required=True, help="Path to config file (yaml/json)"
    )

    status = sub.add_parser("status", help="Show evolve run status")
    status.add_argument("run_id", help="Run id")
    status.add_argument(
        "--config", required=True, help="Path to config file (yaml/json)"
    )

    inspect = sub.add_parser("inspect", help="Inspect an evolve run (full event log)")
    inspect.add_argument("run_id", help="Run id")
    inspect.add_argument(
        "--config", required=True, help="Path to config file (yaml/json)"
    )

    resume = sub.add_parser("resume", help="Resume a paused or interrupted run")
    resume.add_argument("run_id", help="Run id")
    resume.add_argument(
        "--config", required=True, help="Path to config file (yaml/json)"
    )

    pause = sub.add_parser("pause", help="Pause a running evolve optimization")
    pause.add_argument("run_id", help="Run id")
    pause.add_argument(
        "--config", required=True, help="Path to config file (yaml/json)"
    )

    stop = sub.add_parser("stop", help="Stop a running evolve optimization")
    stop.add_argument("run_id", help="Run id")
    stop.add_argument("--config", required=True, help="Path to config file (yaml/json)")

    answer = sub.add_parser("answer", help="Answer a human escalation with guidance")
    answer.add_argument("run_id", help="Run id")
    answer.add_argument(
        "text",
        nargs="?",
        help="Guidance injected as a supervisor directive (omit with --decline)",
    )
    answer.add_argument(
        "--config", required=True, help="Path to config file (yaml/json)"
    )
    answer.add_argument(
        "--decline",
        action="store_true",
        help="Decline to guide: stops the run cleanly as human_declined",
    )

    report = sub.add_parser("report", help="Render the trajectory report from events")
    report.add_argument("run_id", help="Run id")
    report.add_argument(
        "--config", required=True, help="Path to config file (yaml/json)"
    )

    args = parser.parse_args(argv)
    if args.evolve_command == "answer" and not args.decline and not args.text:
        parser.error("answer requires guidance text, or --decline to stop the run")
    agent_bootstrap.register_builtin_agents()

    if args.evolve_command == "validate":
        return _evolve_validate(args.config)

    orch = None
    try:
        if args.evolve_command in {"status", "inspect", "report"}:
            from freemad.evolve.store import EvolveStore

            try:
                cfg = load_config(path=args.config)
            except ConfigError as e:
                print(f"config error: {e}", file=sys.stderr)
                return 2
            store_path = Path(cfg.evolve.store_path)
            if not store_path.exists():
                print(
                    f"config error: no evolve store at {store_path}; "
                    f"no run has been started with this config",
                    file=sys.stderr,
                )
                return 2
            store = EvolveStore(store_path, read_only=True)
            try:
                snapshot = store.get_run(args.run_id)
                if snapshot is None:
                    print(
                        f"config error: unknown evolve run id: {args.run_id}",
                        file=sys.stderr,
                    )
                    return 2
                if args.evolve_command == "report":
                    from freemad.evolve.report import render_report

                    rendered = render_report(store, args.run_id)
                    print(rendered)
                    return 0
                payload: dict[str, Any] = {**snapshot.to_dict()}
                if args.evolve_command == "inspect":
                    payload["events"] = [
                        event.to_dict() for event in store.list_events(args.run_id)
                    ]
            finally:
                store.close()
            print(json.dumps(payload))
            return 0

        try:
            cfg = load_config(path=args.config)
        except ConfigError as e:
            print(f"config error: {e}", file=sys.stderr)
            return 2
        orch = EvolveOrchestrator(cfg)

        if args.evolve_command == "start":
            snapshot = orch.create_run(args.goal)
            print(f"run_id: {snapshot.run_id}", file=sys.stderr, flush=True)
            snapshot = orch.resume(snapshot.run_id)
            final = orch.run(snapshot.run_id)
            print(json.dumps(final.to_dict()))
            return 0 if final.status == EvolveRunStatus.COMPLETED else 1

        if args.evolve_command in {"resume", "pause", "stop"}:
            run_id = args.run_id
            if not _run_exists(orch, run_id):
                print(f"config error: unknown evolve run id: {run_id}", file=sys.stderr)
                return 2
            if args.evolve_command == "resume":
                orch.resume(run_id)
                final = orch.run(run_id)
                print(json.dumps(final.to_dict()))
                return 0 if final.status == EvolveRunStatus.COMPLETED else 1
            if args.evolve_command == "pause":
                updated = orch.pause(run_id)
            else:
                updated = orch.stop(run_id, EvolveStopReason.MANUAL)
            print(json.dumps(updated.to_dict()))
            return 0

        if args.evolve_command == "answer":
            run_id = args.run_id
            if not _run_exists(orch, run_id):
                print(f"config error: unknown evolve run id: {run_id}", file=sys.stderr)
                return 2
            if getattr(args, "decline", False):
                updated = orch.decline(run_id)
                print(json.dumps(updated.to_dict()))
                return 0
            orch.answer(run_id, args.text)
            final = orch.run(run_id)
            print(json.dumps(final.to_dict()))
            return 0 if final.status == EvolveRunStatus.COMPLETED else 1

    except ConfigError as e:
        print(f"evolve error: {e}", file=sys.stderr)
        return 2
    except Exception as e:  # noqa: BLE001 - CLI boundary
        print(f"evolve runtime error: {e}", file=sys.stderr)
        return 1
    finally:
        if orch is not None:
            orch.close()
    return 2


def _evolve_validate(config_path: str) -> int:
    try:
        cfg = load_config(path=config_path)
    except ConfigError as e:
        print(json.dumps({"ok": False, "stage": "config", "error": str(e)}))
        return 2

    problems: list[str] = []
    warnings: list[str] = []
    if not cfg.evolve.judge.stages:
        problems.append("no judge stages configured under evolve.judge.stages")
    if cfg.evolve.variation.kind == VariationKind.SINGLE_AGENT and not (
        cfg.evolve.variation.agent_id and cfg.evolve.variation.agent_id.strip()
    ):
        problems.append(
            "evolve.variation.agent_id is required for single_agent variation"
        )

    lineage: Lineage | None = None
    if not problems:
        lineage = Lineage(cfg, "validate")
        try:
            lineage.require_clean_repo()
            lineage.resolve_ref(cfg.evolve.seed_ref)
        except (ConfigError, LineageError) as e:
            problems.append(str(e))

    if not problems and lineage is not None:
        import tempfile

        with tempfile.TemporaryDirectory() as td:
            worktree = Path(td) / "seed"
            proc_worktree = subprocess.run(
                [
                    "git",
                    "worktree",
                    "add",
                    "--detach",
                    str(worktree),
                    cfg.evolve.seed_ref,
                ],
                cwd=str(lineage.repo_root),
                text=True,
                capture_output=True,
            )
            if proc_worktree.returncode != 0:
                problems.append(f"seed worktree failed: {proc_worktree.stderr.strip()}")
            else:
                try:
                    verdict = Judge(cfg).judge_worktree(worktree)
                finally:
                    subprocess.run(
                        ["git", "worktree", "remove", "--force", str(worktree)],
                        cwd=str(lineage.repo_root),
                        text=True,
                        capture_output=True,
                    )
                # A stage failure is reported on its own: the gate can pass on the
                # partial score vector left behind when a later stage short-circuits,
                # which would otherwise let `validate` bless a broken judge.
                if verdict.failed_stage:
                    problems.append(
                        f"seed judge stage '{verdict.failed_stage}' fails: "
                        f"{enforce_size((verdict.failure_detail or '').strip(), 300, 'seed_detail')[0]}"
                    )
                if not verdict.gate_passed:
                    problems.append(
                        "seed fails its own gate: "
                        + "; ".join(f.describe() for f in verdict.gate_failures)
                    )
                if (
                    not problems
                    and verdict.score is not None
                    and target_met(verdict.score, cfg.evolve.stop.target)
                ):
                    warnings.append(
                        "seed already satisfies stop.target; run would end immediately"
                    )

    var = cfg.evolve.variation
    if var.kind == VariationKind.DEBATE:
        # A debate is N agent calls, not one: every agent generates, every agent
        # critiques each round, then the winner implements. `scope_worker_budget` caps
        # each *call* at the whole iteration budget, so a config can be arithmetically
        # unable to finish a single iteration — which is exactly how a live run spent
        # 600s producing nothing.
        debaters = len(var.debate_agent_ids) or len(
            [a for a in cfg.agents if a.enabled]
        )
        calls = debaters * (1 + max(1, var.debate_rounds)) + 1
        per_call = max((a.timeout or 60.0) for a in cfg.agents if a.enabled)
        budget_sec = cfg.evolve.worker_budget.max_minutes * 60
        if per_call * calls > budget_sec:
            warnings.append(
                f"debate variation needs about {calls} agent calls per iteration "
                f"({debaters} agents x {max(1, var.debate_rounds)} round(s) + implementer), "
                f"but one call may take {per_call:.0f}s against a "
                f"{budget_sec}s worker_budget. Lower agent timeout to about "
                f"{budget_sec // calls}s or raise worker_budget.max_minutes to about "
                f"{(per_call * calls) // 60 + 1}."
            )

    container = cfg.evolve.judge.container
    if container.enabled:
        from freemad.evolve.container import runtime_available

        reason = runtime_available(container.runtime)
        if reason is not None:
            problems.append(
                f"judge.container.enabled is true but {reason}; the run would abort "
                f"rather than fall back to the host"
            )
    else:
        warnings.append(
            "judge.container.enabled is false: judge stages will execute worker-authored "
            "code on the host, with $HOME readable — including the agent CLI's own "
            "session credentials. Enable it for anything but a repo you fully trust."
        )

    for warning in _steerable_stage_warnings(cfg):
        warnings.append(warning)

    for stage_name in _unprotected_scoring_stages(cfg):
        warnings.append(
            f"judge stage '{stage_name}' provides scored components but its command does "
            f"not reference any protected path; the worker can edit the measurement"
        )

    if cfg.evolve.worker_budget.max_turns is not None:
        warnings.append(
            "worker_budget.max_turns is set but no adapter reports turn counts; "
            "worker_budget.max_minutes is the effective per-call bound"
        )

    if cfg.evolve.stop.max_total_cost_usd is not None:
        warnings.append(
            "max_total_cost_usd is set but adapters do not report cost; wall clock is the effective budget"
        )

    result = {"ok": not problems, "problems": problems, "warnings": warnings}
    print(json.dumps(result))
    return 0 if not problems else 2


def _run_exists(orch: EvolveOrchestrator, run_id: str) -> bool:
    try:
        orch.status(run_id)
    except ConfigError:
        return False
    return True


# Files that silently redirect a test runner from OUTSIDE the directory it is pointed
# at: a root conftest.py applies to everything beneath it, and each of these can
# deselect, skip, or neutralise a suite without touching the suite.
_STEERING_FILES = (
    "conftest.py",
    "pytest.ini",
    "tox.ini",
    "setup.cfg",
    "pyproject.toml",
)


def _steerable_stage_warnings(cfg: Any) -> list[str]:
    """Protecting `tests/` does not protect the *decision* to run those tests.

    `_unprotected_scoring_stages` is satisfied as soon as a stage command mentions a
    protected path, which is exactly the shape (`pytest tests` + `protected_paths:
    [tests/]`) a root-level `conftest.py` can empty out.
    """
    protected = {p.rstrip("/") for p in cfg.evolve.judge.protected_paths}
    unprotected = [name for name in _STEERING_FILES if name not in protected]
    if not unprotected:
        return []
    runners = [
        stage.name
        for stage in cfg.evolve.judge.stages
        if "pytest" in stage.command or "tox" in stage.command
    ]
    if not runners:
        return []
    return [
        f"judge stage(s) {', '.join(runners)} run a test runner, but "
        f"{', '.join(unprotected)} are worker-editable; a root-level conftest.py can "
        f"deselect every test without touching a protected path"
    ]


def _unprotected_scoring_stages(cfg: Any) -> list[str]:
    """Scoring stages whose command does not obviously reference a protected path.

    `evolve.md` section 2.2: every scored component must derive from at least one
    protected stage, or the measured can edit the measurement. Path matching is a
    heuristic (a stage may score through a Makefile or an installed entry point), so
    this warns rather than failing the config.
    """
    protected = [
        PurePosixPath(p.rstrip("/"))
        for p in cfg.evolve.judge.protected_paths
        if p.strip()
    ]
    unprotected: list[str] = []
    for stage in cfg.evolve.judge.stages:
        if not stage.provides:
            continue
        try:
            tokens = shlex.split(stage.command)
        except ValueError:
            tokens = stage.command.split()
        touches = False
        for token in tokens:
            stripped = token.lstrip("./")
            if not stripped:
                # A bare "." is an ancestor of every relative path. Treating an ancestor
                # as evidence blessed `pytest . --benchmark-json=o.json` against any
                # protected path at all -- the single most common scoring invocation.
                continue
            candidate = PurePosixPath(stripped)
            for prot in protected:
                if candidate == prot or prot in candidate.parents:
                    touches = True
                    break
            if touches:
                break
        if not touches:
            unprotected.append(stage.name)
    return unprotected


def main(argv: list[str] | None = None) -> int:
    argv_list = list(argv) if argv is not None else sys.argv[1:]
    if argv_list and argv_list[0] == "task":
        agent_bootstrap.register_builtin_agents()
        return _task_main(argv_list[1:])
    if argv_list and argv_list[0] == "evolve":
        return _evolve_main(argv_list[1:])

    parser = argparse.ArgumentParser(
        prog="freemad", description="FREE-MAD Orchestrator CLI"
    )
    parser.add_argument("requirement", nargs="?", help="Problem statement to solve")
    parser.add_argument("--config", help="Path to config file (yaml/json)")
    parser.add_argument(
        "--rounds", type=int, default=1, help="Number of critique rounds"
    )
    parser.add_argument(
        "--save-transcript", action="store_true", help="Force saving transcript"
    )
    parser.add_argument(
        "--format", choices=["json", "markdown"], help="Transcript format override"
    )
    parser.add_argument("--transcript-dir", help="Transcript directory override")
    parser.add_argument("--verbose", action="store_true")
    parser.add_argument("--version", action="store_true", help="Print version and exit")
    parser.add_argument(
        "--health", action="store_true", help="Print agent health and exit"
    )

    args = parser.parse_args(argv_list or None)

    agent_bootstrap.register_builtin_agents()

    if args.version:
        print(PACKAGE_VERSION)
        return 0

    # Build a single overrides dict for load_config
    overrides: dict[str, dict[str, Any]] = {}
    if args.transcript_dir:
        overrides.setdefault("output", {})["transcript_dir"] = args.transcript_dir
    if args.format:
        overrides.setdefault("output", {})["format"] = args.format
    try:
        cfg = load_config(
            path=args.config if args.config else None, overrides=overrides or None
        )
    except ConfigError as e:
        print(f"config error: {e}", file=sys.stderr)
        return 2

    if args.health:
        from freemad.agents.factory import AgentFactory

        factory = AgentFactory(cfg)
        agents = factory.build_all()
        for aid, a in agents.items():
            h = a.health()
            status = "ok" if h.available else "unavailable"
            print(f"{aid}: {status} - {h.message or ''} {h.version or ''}")

        return 0

    if not args.requirement:
        print("requirement is required unless --health/--version", file=sys.stderr)
        return 2

    orch = Orchestrator(cfg)
    try:
        result = orch.run(args.requirement, max_rounds=args.rounds)
    except ConfigError as e:
        print(
            "config error during run: "
            + str(e)
            + "\nHint: configure agents[].cli_command and allowlist via security.cli_allowed_commands, or use a mock config (examples/mock_agents.yaml).",
            file=sys.stderr,
        )
        return 2

    # Summary
    print("FREE-MAD result")
    final_id = result["final_answer_id"]
    final_score = result["scores"].get(final_id, 0.0)
    rounds = max(0, len(result["transcript"]) - 1)
    print(f"- Final answer id: {final_id}")
    print(f"- Final score: {final_score:.2f}")
    print(f"- Rounds: {rounds}")
    print(f"- Winning agents: {', '.join(result['winning_agents'])}")
    print(f"- Topology: {result['transcript'][0]['topology_info']}")

    # Save transcript if configured or forced
    save = args.save_transcript or cfg.output.save_transcript
    if save:
        fmt = args.format or cfg.output.format
        path = save_transcript(
            result, fmt, args.transcript_dir or cfg.output.transcript_dir
        )
        if args.verbose:
            print(f"Transcript saved to: {path}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
