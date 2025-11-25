from __future__ import annotations

import argparse
import sys
from typing import Any

from freemad.agents import bootstrap as agent_bootstrap
from freemad.config import ConfigError, load_config
from freemad.orchestrator import Orchestrator
from freemad.utils.transcript import save_transcript


PACKAGE_VERSION = "0.1.0"


def main(argv: list[str] | None = None) -> int:
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

    args = parser.parse_args(argv)

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
