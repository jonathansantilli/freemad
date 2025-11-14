import os
import unittest

from freemad import load_config
from freemad import Orchestrator


@unittest.skipUnless(os.getenv("SMOKE") == "1", "smoke test disabled; set SMOKE=1 to enable")
class TestSmokeAdapters(unittest.TestCase):
    def test_cli_adapters_with_mock_agent(self):
        cfg = load_config(overrides={
            "agents": [
                {"id": "a", "type": "claude_code", "cli_command": "python bin/mock_agent.py"},
                {"id": "b", "type": "openai_codex", "cli_command": "python bin/mock_agent.py --force-revise"}
            ],
            "security": {"cli_allowed_commands": ["python"]},
            "deadlines": {"soft_timeout_ms": 200, "hard_timeout_ms": 500, "min_agents": 2}
        })
        orch = Orchestrator(cfg)
        out = orch.run("echo", max_rounds=1)
        self.assertIn("final_answer_id", out)
        # b must have revised
        crit = out["transcript"][1]
        self.assertEqual(crit["agents"]["b"]["response"]["decision"], "REVISE")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
