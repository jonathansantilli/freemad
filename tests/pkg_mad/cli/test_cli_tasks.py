from __future__ import annotations

import json
from pathlib import Path

from freemad import register_agent
from freemad.cli import main
from tests.pkg_mad.tasks.test_orchestrator import _QuorumMockAgent


def _write_task_config(tmp_path: Path) -> Path:
    cfg_path = tmp_path / "cfg.json"
    cfg_path.write_text(
        json.dumps(
            {
                "agents": [
                    {"id": "researcher-a", "type": "quorum_mock", "roles": ["researcher"]},
                    {"id": "planner-a", "type": "quorum_mock", "roles": ["planner"]},
                    {"id": "reviewer-a", "type": "quorum_mock", "roles": ["reviewer"]},
                    {"id": "implementer-a", "type": "quorum_mock", "roles": ["implementer"]},
                    {"id": "verifier-a", "type": "quorum_mock", "roles": ["verifier"]},
                    {"id": "arbiter-a", "type": "quorum_mock", "roles": ["arbiter"]},
                ],
                "task": {
                    "store_path": str(tmp_path / "tasks.db"),
                    "artifacts_dir": str(tmp_path / "artifacts"),
                    "max_stage_retries": 0,
                    "tool_policy": {
                        "allow_workspace_write": True,
                        "allowed_write_roots": ["src"],
                        "allow_local_commands": False,
                        "verification_commands": [],
                    },
                },
            }
        ),
        encoding="utf-8",
    )
    return cfg_path


def test_task_start_status_and_inspect(capsys, tmp_path: Path) -> None:
    register_agent("quorum_mock", _QuorumMockAgent)
    cfg_path = _write_task_config(tmp_path)
    workspace = tmp_path / "workspace-plan"
    workspace.mkdir()

    rc = main(
        [
            "task",
            "start",
            "--config",
            str(cfg_path),
            "--task-type",
            "plan",
            "--workspace-root",
            str(workspace),
            "Solidify the implementation plan.",
        ]
    )
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "completed"
    task_id = payload["task_id"]

    rc = main(["task", "status", "--config", str(cfg_path), task_id])
    assert rc == 0
    status_payload = json.loads(capsys.readouterr().out)
    assert status_payload["task_id"] == task_id
    assert status_payload["status"] == "completed"

    rc = main(["task", "inspect", "--config", str(cfg_path), task_id])
    assert rc == 0
    inspect_payload = json.loads(capsys.readouterr().out)
    assert inspect_payload["task_id"] == task_id
    assert inspect_payload["artifacts"]
    assert inspect_payload["events"]


def test_task_answer_approve_pause_and_resume(capsys, tmp_path: Path) -> None:
    register_agent("quorum_mock", _QuorumMockAgent)
    cfg_path = _write_task_config(tmp_path)
    workspace = tmp_path / "workspace-human"
    workspace.mkdir()

    rc = main(
        [
            "task",
            "start",
            "--config",
            str(cfg_path),
            "--task-type",
            "plan",
            "--workspace-root",
            str(workspace),
            "Human clarification is required for this plan.",
        ]
    )
    assert rc == 0
    start_payload = json.loads(capsys.readouterr().out)
    assert start_payload["status"] == "waiting_for_human"
    task_id = start_payload["task_id"]

    rc = main(["task", "answer", "--config", str(cfg_path), task_id, "Use SQLite."])
    assert rc == 0
    answer_payload = json.loads(capsys.readouterr().out)
    assert answer_payload["task_id"] == task_id
    assert any(event["kind"] == "human_input_received" for event in answer_payload["events"])

    rc = main(["task", "approve", "--config", str(cfg_path), task_id, "plan_review"])
    assert rc == 0
    approve_payload = json.loads(capsys.readouterr().out)
    assert approve_payload["task_id"] == task_id
    assert any(event["kind"] == "decision_recorded" for event in approve_payload["events"])

    rc = main(["task", "pause", "--config", str(cfg_path), task_id])
    assert rc == 0
    pause_payload = json.loads(capsys.readouterr().out)
    assert pause_payload["status"] == "paused"

    rc = main(["task", "resume", "--config", str(cfg_path), task_id])
    assert rc == 0
    resume_payload = json.loads(capsys.readouterr().out)
    assert resume_payload["task_id"] == task_id
    assert resume_payload["status"] in {"waiting_for_human", "completed"}
