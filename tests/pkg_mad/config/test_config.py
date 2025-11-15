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


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
