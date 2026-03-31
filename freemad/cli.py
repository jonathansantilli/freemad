from __future__ import annotations

import argparse
import json
import sys
from dataclasses import replace
from typing import Any

from freemad.agents import bootstrap as agent_bootstrap
from freemad.config import ConfigError, load_config
from freemad.orchestrator import Orchestrator
from freemad.task_events import TaskEvent
from freemad.tasks.orchestrator import TaskOrchestrator
from freemad.types import TaskEventKind, TaskStatus, TaskType
from freemad.utils.transcript import save_transcript


PACKAGE_VERSION = "0.1.0"


def _task_payload(orch: TaskOrchestrator, task_id: str) -> dict[str, Any]:
    task = orch.get_task(task_id)
    if task is None:
        raise ConfigError(f"unknown task id: {task_id}")
    return {
        **task.to_dict(),
        "artifacts": [artifact.to_dict() for artifact in orch.store.list_artifacts(task_id)],
        "work_items": [item.to_dict() for item in orch.store.list_work_items(task_id)],
        "events": [event.to_dict() for event in orch.store.list_events(task_id)],
    }


def _task_main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="freemad task", description="FREE-MAD autonomous task CLI")
    sub = parser.add_subparsers(dest="task_command", required=True)

    start = sub.add_parser("start", help="Create and run a new autonomous task")
    start.add_argument("goal", help="Task goal")
    start.add_argument("--config", help="Path to config file (yaml/json)")
    start.add_argument("--task-type", choices=[TaskType.PLAN.value, TaskType.CODE.value], default=TaskType.PLAN.value)
    start.add_argument("--workspace-root", default=".", help="Workspace root for autonomous task execution")

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
            if existing_task.status in {TaskStatus.PAUSED, TaskStatus.WAITING_FOR_HUMAN}:
                orch.store.update_task(replace(existing_task, status=TaskStatus.RUNNING))
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


def main(argv: list[str] | None = None) -> int:
    argv_list = list(argv) if argv is not None else sys.argv[1:]
    if argv_list and argv_list[0] == "task":
        agent_bootstrap.register_builtin_agents()
        return _task_main(argv_list[1:])

    parser = argparse.ArgumentParser(prog="freemad", description="FREE-MAD Orchestrator CLI")
    parser.add_argument("requirement", nargs="?", help="Problem statement to solve")
    parser.add_argument("--config", help="Path to config file (yaml/json)")
    parser.add_argument("--rounds", type=int, default=1, help="Number of critique rounds")
    parser.add_argument("--save-transcript", action="store_true", help="Force saving transcript")
    parser.add_argument("--format", choices=["json", "markdown"], help="Transcript format override")
    parser.add_argument("--transcript-dir", help="Transcript directory override")
    parser.add_argument("--verbose", action="store_true")
    parser.add_argument("--version", action="store_true", help="Print version and exit")
    parser.add_argument("--health", action="store_true", help="Print agent health and exit")

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
        cfg = load_config(path=args.config if args.config else None, overrides=overrides or None)
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
    final_id = result['final_answer_id']
    final_score = result['scores'].get(final_id, 0.0)
    rounds = max(0, len(result['transcript']) - 1)
    print(f"- Final answer id: {final_id}")
    print(f"- Final score: {final_score:.2f}")
    print(f"- Rounds: {rounds}")
    print(f"- Winning agents: {', '.join(result['winning_agents'])}")
    print(f"- Topology: {result['transcript'][0]['topology_info']}")

    # Save transcript if configured or forced
    save = args.save_transcript or cfg.output.save_transcript
    if save:
        fmt = args.format or cfg.output.format
        path = save_transcript(result, fmt, args.transcript_dir or cfg.output.transcript_dir)
        if args.verbose:
            print(f"Transcript saved to: {path}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
