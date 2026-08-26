from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import subprocess

from freemad.agents.cli_adapter import CLIAdapter
from freemad.config import (
    AgentConfig,
    AgentRuntimeConfig,
    Config,
    SecurityConfig,
    BudgetConfig,
)


class DummyAdapter(CLIAdapter):
    pass


def test_cli_args_are_appended(monkeypatch):
    cfg = Config(
        agents=[],
        security=SecurityConfig(cli_allowed_commands=["mycmd"]),
        budget=BudgetConfig(max_agent_time_sec=10.0),
    )
    agent_cfg = AgentConfig(
        id="a1",
        type="custom",
        enabled=True,
        cli_command="mycmd",
        timeout=5.0,
        config=AgentRuntimeConfig(temperature=0.0, max_tokens=None),
        cli_args={"model": "gpt", "-X": "42"},
    )

    called = {}

    def fake_run(
        cmd: list[str],
        input: str,
        text: bool,
        capture_output: bool,
        timeout: float,
        check: bool,
    ) -> Any:  # noqa: A002
        called["cmd"] = cmd
        # stdout with both markers so parser accepts
        return SimpleNamespace(
            stdout="SOLUTION:\nok\n\nREASONING:\nwhy", stderr="", returncode=0
        )

    monkeypatch.setattr(subprocess, "run", fake_run)

    a = DummyAdapter(cfg, agent_cfg)
    a.generate("do it")

    # Expect deterministic ordering: '-X' comes before '--model' because of sort
    assert called["cmd"][0] == "mycmd"
    assert called["cmd"][1:5] == ["-X", "42", "--model", "gpt"]


def test_mode_flags_apply_per_call_mode(monkeypatch):
    """Debate thinking modes can run without tools; act() keeps them.

    Against a real repository an agent with tools spends minutes on find/grep/read
    before writing a plan, and every generation call times out. `--tools ""` on the
    generating/critique modes -- and only there -- is what bounds a plan debate.
    """
    from freemad.agents import bootstrap
    from freemad.agents.factory import AgentFactory
    from freemad.config import load_config

    bootstrap.register_builtin_agents()
    cfg = load_config(
        overrides={
            "agents": [
                {
                    "id": "w",
                    "type": "claude_code",
                    "cli_command": "claude -p",
                    "cli_mode_flags": {
                        "generating": ["--tools", ""],
                        "critique": ["--tools", ""],
                    },
                },
                {"id": "x", "type": "openai_codex"},
            ]
        }
    )
    agent = AgentFactory(cfg).build_all()["w"]
    calls = []

    class Done:
        returncode = 0
        stdout = "SOLUTION: x\nREASONING: y"
        stderr = ""

    def fake(cmd, **_):
        calls.append(list(cmd))
        return Done()

    monkeypatch.setattr("freemad.agents.cli_adapter.subprocess.run", fake)
    for mode in ("generating", "critique", "task-execute"):
        agent._run_cli("hi", mode=mode)

    assert calls[0][-2:] == ["--tools", ""], "generate must run without tools"
    assert calls[1][-2:] == ["--tools", ""], "critique must run without tools"
    assert "--tools" not in calls[2], "act() must keep its tools"


def test_mode_flag_family_covers_every_task_stage(monkeypatch):
    """A "task" key applies to task-execute, task-review, task-plan..."""
    from freemad.agents import bootstrap
    from freemad.agents.factory import AgentFactory
    from freemad.config import load_config

    bootstrap.register_builtin_agents()
    cfg = load_config(
        overrides={
            "agents": [
                {
                    "id": "w",
                    "type": "claude_code",
                    "cli_command": "claude -p",
                    "cli_mode_flags": {"task": ["--max-turns", "40"]},
                },
                {"id": "x", "type": "openai_codex"},
            ]
        }
    )
    agent = AgentFactory(cfg).build_all()["w"]
    calls = []

    class Done:
        returncode = 0
        stdout = "{}"
        stderr = ""

    monkeypatch.setattr(
        "freemad.agents.cli_adapter.subprocess.run",
        lambda cmd, **_: (calls.append(list(cmd)), Done())[1],
    )
    agent._run_cli("hi", mode="task-execute")
    agent._run_cli("hi", mode="task-review")
    agent._run_cli("hi", mode="generating")
    assert calls[0][-2:] == ["--max-turns", "40"]
    assert calls[1][-2:] == ["--max-turns", "40"]
    assert "--max-turns" not in calls[2]
