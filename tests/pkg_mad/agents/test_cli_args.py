from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import subprocess

from freemad.agents.cli_adapter import CLIAdapter
from freemad.config import AgentConfig, AgentRuntimeConfig, Config, SecurityConfig, BudgetConfig


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

    def fake_run(cmd: list[str], input: str, text: bool, capture_output: bool, timeout: float, check: bool) -> Any:  # noqa: A002
        called["cmd"] = cmd
        # stdout with both markers so parser accepts
        return SimpleNamespace(stdout="SOLUTION:\nok\n\nREASONING:\nwhy", stderr="", returncode=0)

    monkeypatch.setattr(subprocess, "run", fake_run)

    a = DummyAdapter(cfg, agent_cfg)
    a.generate("do it")

    # Expect deterministic ordering: '-X' comes before '--model' because of sort
    assert called["cmd"][0] == "mycmd"
    assert called["cmd"][1:5] == ["-X", "42", "--model", "gpt"]

