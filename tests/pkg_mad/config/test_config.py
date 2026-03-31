import json
import tempfile
import unittest
from pathlib import Path

from freemad import (
    ConfigError,
    load_config,
)


class TestConfig(unittest.TestCase):
    def test_defaults(self):
        cfg = load_config()
        self.assertEqual(len(cfg.agents), 2)
        self.assertEqual(cfg.agents[0].id, "claude")
        self.assertEqual(cfg.agents[1].id, "codex")
        self.assertEqual(cfg.topology.type, "all_to_all")
        self.assertEqual(cfg.scoring.weights, [20.0, 25.0, 30.0, 20.0])
        self.assertTrue(cfg.scoring.normalize)
        self.assertEqual(cfg.scoring.tie_break, "deterministic")

        # transcript dir should exist
        self.assertTrue(Path(cfg.output.transcript_dir).exists())

    def test_invalid_weights_length(self):
        with self.assertRaises(ConfigError):
            load_config(overrides={"scoring": {"weights": [1, 2, 3]}})

    def test_invalid_topology(self):
        with self.assertRaises(ConfigError):
            load_config(overrides={"topology": {"type": "mesh"}})

    def test_duplicate_agent_ids(self):
        with self.assertRaises(ConfigError):
            load_config(
                overrides={
                    "agents": [
                        {"id": "a", "type": "claude_code"},
                        {"id": "a", "type": "openai_codex"},
                    ]
                }
            )

    def test_deadlines_ordering(self):
        with self.assertRaises(ConfigError):
            load_config(
                overrides={
                    "deadlines": {"soft_timeout_ms": 5000, "hard_timeout_ms": 4000}
                }
            )

    def test_star_topology_requires_hub(self):
        with self.assertRaises(ConfigError):
            load_config(
                overrides={
                    "topology": {"type": "star"},
                }
            )

    def test_k_reviewers_requires_valid_k(self):
        # default 2 agents => k must be 1
        with self.assertRaises(ConfigError):
            load_config(overrides={"topology": {"type": "k_reviewers", "k": 2}})

        cfg = load_config(overrides={"topology": {"type": "k_reviewers", "k": 1}})
        self.assertEqual(cfg.topology.type, "k_reviewers")
        self.assertEqual(cfg.topology.k, 1)

    def test_security_shell_disallowed(self):
        with self.assertRaises(ConfigError):
            load_config(overrides={"security": {"cli_use_shell": True}})

    def test_budget_must_be_positive(self):
        with self.assertRaises(ConfigError):
            load_config(overrides={"budget": {"max_total_time_sec": -1}})

    def test_budget_tokens_must_be_positive_when_enforced(self):
        with self.assertRaises(ConfigError):
            load_config(overrides={"budget": {"enforce_total_tokens": True, "max_total_tokens": -5}})

    def test_invalid_yaml_file_raises(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg_path = Path(tmp) / "bad.yaml"
            cfg_path.write_text("agents: [", encoding="utf-8")
            with self.assertRaises(ConfigError):
                load_config(path=str(cfg_path))

    def test_k_reviewers_cannot_exceed_agents(self):
        overrides = {
            "agents": [
                {"id": "a", "type": "claude_code", "enabled": True, "cli_command": "python"},
                {"id": "b", "type": "claude_code", "enabled": True, "cli_command": "python"},
                {"id": "c", "type": "claude_code", "enabled": True, "cli_command": "python"},
            ],
            "topology": {"type": "k_reviewers", "k": 3},
        }
        with self.assertRaises(ConfigError):
            load_config(overrides=overrides)

    def test_unknown_agent_type_rejected(self):
        with self.assertRaises(ConfigError):
            load_config(overrides={"agents": [{"id": "x", "type": "unknown_adapter"}]})

    def test_load_from_json_file_and_override(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg_path = Path(tmp) / "cfg.json"
            data = {
                "output": {
                    "save_transcript": True,
                    "transcript_dir": str(Path(tmp) / "t_out"),
                    "format": "markdown",
                }
            }
            cfg_path.write_text(json.dumps(data), encoding="utf-8")

            cfg = load_config(path=str(cfg_path), overrides={"output": {"verbose": True}})
            self.assertEqual(cfg.output.format, "markdown")
            self.assertTrue(cfg.output.verbose)
            self.assertTrue(Path(cfg.output.transcript_dir).exists())

    def test_autonomous_enums_use_string_values(self):
        from freemad.types import ActionKind, TaskRole, TaskStage, TaskStatus

        self.assertEqual(TaskStage.INTAKE.value, "intake")
        self.assertEqual(TaskStage.VERIFY.value, "verify")
        self.assertEqual(str(TaskRole.PLANNER), "planner")
        self.assertEqual(TaskStatus.WAITING_FOR_HUMAN.value, "waiting_for_human")
        self.assertEqual(ActionKind.RUN_COMMAND.value, "run_command")

    def test_autonomous_task_config_loads_from_yaml(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg_path = Path(tmp) / "autonomous.yaml"
            cfg_path.write_text(
                """
agents:
  - id: planner_a
    type: claude_code
    roles: ["planner", "reviewer"]
  - id: implementer_b
    type: openai_codex
    roles: ["implementer", "verifier"]
task:
  store_path: ".freemad/tasks/tasks.db"
  artifacts_dir: ".freemad/tasks/artifacts"
  max_stage_retries: 3
  max_total_iterations: 12
  tool_policy:
    allow_web_research: true
    allow_workspace_write: true
    allow_local_commands: true
    allowed_write_roots: ["freemad", "tests"]
    allowed_local_commands: ["python3", "pytest"]
    verification_commands: ["pytest -q"]
""".strip(),
                encoding="utf-8",
            )

            cfg = load_config(path=str(cfg_path))

            self.assertEqual(cfg.task.store_path, ".freemad/tasks/tasks.db")
            self.assertEqual(cfg.task.artifacts_dir, ".freemad/tasks/artifacts")
            self.assertEqual(cfg.task.max_stage_retries, 3)
            self.assertEqual(cfg.task.max_total_iterations, 12)
            self.assertEqual([role.value for role in cfg.agents[0].roles], ["planner", "reviewer"])
            self.assertEqual([role.value for role in cfg.agents[1].roles], ["implementer", "verifier"])
            self.assertTrue(cfg.task.tool_policy.allow_web_research)
            self.assertEqual(cfg.task.tool_policy.allowed_write_roots, ["freemad", "tests"])
            self.assertEqual(cfg.task.tool_policy.allowed_local_commands, ["python3", "pytest"])
            self.assertEqual(cfg.task.tool_policy.verification_commands, ["pytest -q"])

    def test_invalid_autonomous_role_is_rejected(self):
        with self.assertRaises(ConfigError):
            load_config(
                overrides={
                    "agents": [
                        {"id": "a", "type": "claude_code", "roles": ["planner", "not-a-role"]},
                        {"id": "b", "type": "openai_codex", "roles": ["reviewer"]},
                    ]
                }
            )


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
