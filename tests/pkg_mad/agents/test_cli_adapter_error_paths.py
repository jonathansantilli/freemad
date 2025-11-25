from __future__ import annotations

from types import SimpleNamespace
from typing import Any, Iterator

import pytest
import subprocess

from freemad.agents.cli_adapter import CLIAdapter
from freemad.config import (
    AgentConfig,
    AgentRuntimeConfig,
    BudgetConfig,
    Config,
    ConfigError,
    SecurityConfig,
)


def _base_config(cli_command: str, allowed: list[str]) -> tuple[Config, AgentConfig]:
    cfg = Config(
        agents=[],
        security=SecurityConfig(cli_allowed_commands=allowed),
        budget=BudgetConfig(max_agent_time_sec=5.0),
    )
    agent_cfg = AgentConfig(
        id="a1",
        type="custom",
        enabled=True,
        cli_command=cli_command,
        timeout=1.0,
        config=AgentRuntimeConfig(temperature=0.0, max_tokens=None),
    )
    return cfg, agent_cfg


def test_cli_command_not_allowlisted_raises():
    cfg, agent_cfg = _base_config("badcmd", ["goodcmd"])
    adapter = CLIAdapter(cfg, agent_cfg)
    with pytest.raises(ConfigError):
        adapter.generate("do it")


def test_cli_timeout_bubbles_up(monkeypatch):
    cfg, agent_cfg = _base_config("safe", ["safe"])
    adapter = CLIAdapter(cfg, agent_cfg)

    def fake_run(*_: Any, **__: Any) -> Any:
        raise subprocess.TimeoutExpired(cmd=["safe"], timeout=1)

    monkeypatch.setattr(subprocess, "run", fake_run)
    with pytest.raises(subprocess.TimeoutExpired):
        adapter.generate("task")


def test_cli_nonzero_return_surfaces_stderr(monkeypatch):
    cfg, agent_cfg = _base_config("safe", ["safe"])
    adapter = CLIAdapter(cfg, agent_cfg)

    def fake_run(*_: Any, **__: Any) -> Any:
        return SimpleNamespace(stdout="", stderr="boom", returncode=9)

    monkeypatch.setattr(subprocess, "run", fake_run)
    resp = adapter.generate("task")
    assert "boom" in resp.solution
    assert resp.metadata.timings.get("cached") == 0.0


def test_cli_cache_hit_short_circuits(monkeypatch):
    cfg, agent_cfg = _base_config("safe", ["safe"])
    adapter = CLIAdapter(cfg, agent_cfg)

    class StubCache:
        def __init__(self) -> None:
            self.value: str | None = None
            self.set_calls: list[tuple[str | None, str]] = []

        def make_key(self, *args: Any, **kwargs: Any) -> str:  # noqa: ARG002
            return "k"

        def get(self, key: str) -> str | None:
            return self.value if key == "k" else None

        def set(self, key: str | None, value: str) -> None:
            self.set_calls.append((key, value))
            self.value = value

    stub_cache = StubCache()
    adapter._cache = stub_cache  # type: ignore[assignment]
    stub_cache.value = "SOLUTION:\ncached\n\nREASONING:\nwhy"

    resp = adapter.generate("task")
    assert resp.solution == "cached"
    assert resp.metadata.timings.get("cached") == 1.0
    # cache was not written on hit
    assert stub_cache.set_calls == []


def test_cli_retry_succeeds_on_second_attempt(monkeypatch):
    cfg, agent_cfg = _base_config("safe", ["safe"])
    adapter = CLIAdapter(cfg, agent_cfg)

    outputs: Iterator[Any] = iter(
        [
            SimpleNamespace(stdout="SOLUTION:\n\nREASONING:\n", stderr="", returncode=0),
            SimpleNamespace(stdout="SOLUTION:\nsecond\n\nREASONING:\nworks", stderr="", returncode=0),
        ]
    )

    def fake_run(*_: Any, **__: Any) -> Any:
        return next(outputs)

    monkeypatch.setattr(subprocess, "run", fake_run)
    resp = adapter.generate("task")
    assert resp.solution == "second"
    # elapsed_ms accumulates both attempts; presence of key implies both attempts executed
    assert resp.metadata.timings["elapsed_ms"] >= 0
