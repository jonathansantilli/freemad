import os
import shlex
import sys
import unittest

from freemad import load_config
from freemad import Orchestrator


@unittest.skipUnless(
    os.getenv("SMOKE") == "1", "smoke test disabled; set SMOKE=1 to enable"
)
class TestSmokeAdapters(unittest.TestCase):
    def test_cli_adapters_with_mock_agent(self):
        # The mock agent runs under *this* interpreter. A bare `python` resolves only
        # with a venv on PATH — which CI's setup-python provides and little else does.
        exe = sys.executable
        mock = f"{shlex.quote(exe)} bin/mock_agent.py"
        cfg = load_config(
            overrides={
                "agents": [
                    {
                        "id": "a",
                        "type": "claude_code",
                        "cli_command": mock,
                        "cli_mode_arg": True,
                    },
                    {
                        "id": "b",
                        "type": "openai_codex",
                        "cli_command": mock,
                        "cli_mode_arg": True,
                        "cli_flags": ["--force-revise"],
                    },
                ],
                "security": {"cli_allowed_commands": [exe]},
                "deadlines": {
                    "soft_timeout_ms": 200,
                    "hard_timeout_ms": 500,
                    "min_agents": 2,
                },
            }
        )
        orch = Orchestrator(cfg)
        out = orch.run("echo", max_rounds=1)
        self.assertIn("final_answer_id", out)
        # b must have revised
        crit = out["transcript"][1]
        self.assertEqual(crit["agents"]["b"]["response"]["decision"], "REVISE")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
