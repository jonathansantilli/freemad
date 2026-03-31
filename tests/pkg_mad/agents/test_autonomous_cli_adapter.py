from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import subprocess

from freemad.agents.cli_adapter import CLIAdapter
from freemad.config import AgentConfig, AgentRuntimeConfig, BudgetConfig, Config, SecurityConfig
from freemad.tasks.models import TaskRequest, WorkItem
from freemad.types import ActionKind, ReviewDecision, TaskRole, TaskStage, WorkItemStatus


class DummyAdapter(CLIAdapter):
    pass


def _build_adapter() -> DummyAdapter:
    cfg = Config(
        agents=[],
        security=SecurityConfig(cli_allowed_commands=["mycmd"]),
        budget=BudgetConfig(max_agent_time_sec=10.0),
    )
    agent_cfg = AgentConfig(
        id="worker",
        type="custom",
        enabled=True,
        cli_command="mycmd",
        timeout=5.0,
        config=AgentRuntimeConfig(temperature=0.0, max_tokens=None),
    )
    return DummyAdapter(cfg, agent_cfg)


def test_build_task_prompt_embeds_stage_role_and_actions() -> None:
    from freemad.prompts import build_task_prompt

    request = TaskRequest(
        task_id="task-1",
        goal="Implement the approved plan.",
        stage=TaskStage.EXECUTE,
        role=TaskRole.IMPLEMENTER,
        workspace_root="/repo",
        allowed_actions=(ActionKind.WRITE_FILE, ActionKind.RUN_COMMAND),
        work_item=WorkItem(
            work_item_id="w-1",
            task_id="task-1",
            title="Create store",
            description="Add task store.",
            status=WorkItemStatus.QUEUED,
        ),
    )

    prompt = build_task_prompt(request)

    assert "Return exactly one JSON object" in prompt
    assert '"stage": "execute"' in prompt
    assert '"role": "implementer"' in prompt
    assert '"allowed_actions"' in prompt
    assert '"write_file"' in prompt
    assert '"run_command"' in prompt


def test_cli_adapter_act_parses_structured_json(monkeypatch) -> None:
    adapter = _build_adapter()
    request = TaskRequest(
        task_id="task-1",
        goal="Review the change.",
        stage=TaskStage.CODE_REVIEW,
        role=TaskRole.REVIEWER,
        workspace_root="/repo",
        allowed_actions=(ActionKind.REVIEW,),
    )

    def fake_run(cmd: list[str], input: str, text: bool, capture_output: bool, timeout: float, check: bool) -> Any:  # noqa: A002
        assert cmd[0] == "mycmd"
        assert '"stage": "code_review"' in input
        return SimpleNamespace(
            stdout=(
                '{"agent_id":"worker","stage":"code_review","role":"reviewer",'
                '"content":"Patch needs tests.","review_decision":"revise",'
                '"findings":["missing tests"],"commands":["pytest -q"],'
                '"work_items":[{"work_item_id":"w-1","task_id":"task-1","title":"Add tests",'
                '"description":"Add missing tests.","status":"queued"}]}'
            ),
            stderr="",
            returncode=0,
        )

    monkeypatch.setattr(subprocess, "run", fake_run)

    response = adapter.act(request)

    assert response.agent_id == "worker"
    assert response.stage == TaskStage.CODE_REVIEW
    assert response.role == TaskRole.REVIEWER
    assert response.review_decision == ReviewDecision.REVISE
    assert response.findings == ("missing tests",)
    assert response.commands == ("pytest -q",)
    assert len(response.work_items) == 1
    assert response.work_items[0].status == WorkItemStatus.QUEUED


def test_cli_adapter_act_parses_structured_sources(monkeypatch) -> None:
    adapter = _build_adapter()
    request = TaskRequest(
        task_id="task-1",
        goal="Research the architecture.",
        stage=TaskStage.RESEARCH,
        role=TaskRole.RESEARCHER,
        workspace_root="/repo",
        allowed_actions=(ActionKind.RESEARCH,),
    )

    def fake_run(cmd: list[str], input: str, text: bool, capture_output: bool, timeout: float, check: bool) -> Any:  # noqa: A002
        assert '"stage": "research"' in input
        return SimpleNamespace(
            stdout=(
                '{"agent_id":"worker","stage":"research","role":"researcher",'
                '"content":"Research bundle","sources":[{"title":"FREE-MAD paper",'
                '"url":"https://arxiv.org/html/2509.11035v1",'
                '"summary":"Consensus-free debate."}]}'
            ),
            stderr="",
            returncode=0,
        )

    monkeypatch.setattr(subprocess, "run", fake_run)

    response = adapter.act(request)

    assert len(response.sources) == 1
    assert response.sources[0].title == "FREE-MAD paper"
    assert response.sources[0].url == "https://arxiv.org/html/2509.11035v1"


def test_existing_debate_prompt_contract_remains_unchanged(monkeypatch) -> None:
    adapter = _build_adapter()

    def fake_run(cmd: list[str], input: str, text: bool, capture_output: bool, timeout: float, check: bool) -> Any:  # noqa: A002
        assert "SOLUTION:" in input
        assert "REASONING:" in input
        return SimpleNamespace(stdout="SOLUTION:\nok\n\nREASONING:\nwhy", stderr="", returncode=0)

    monkeypatch.setattr(subprocess, "run", fake_run)

    response = adapter.generate("do it")

    assert response.solution == "ok"
    assert response.reasoning == "why"
