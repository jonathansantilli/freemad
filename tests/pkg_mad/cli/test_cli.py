import io
import json
import sys
import unittest
import tempfile
from pathlib import Path

from freemad import main
from freemad import register_agent
from freemad import Agent, AgentResponse, CritiqueResponse, Metadata
from freemad import Decision
from freemad import compute_answer_id


class _CliMockAgent(Agent):
    def generate(self, requirement: str) -> AgentResponse:
        sol = f"CLI_{self.agent_cfg.id}"
        return AgentResponse(self.agent_cfg.id, sol, "r", compute_answer_id(sol), Metadata())

    def critique_and_refine(self, requirement: str, own_response: str, peer_responses):
        return CritiqueResponse(self.agent_cfg.id, Decision.KEEP, False, own_response, "r", compute_answer_id(own_response), Metadata())


class TestCLI(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        register_agent("cli_mock", _CliMockAgent)

    def capture(self, argv):
        buf = io.StringIO()
        old_out = sys.stdout
        try:
            sys.stdout = buf
            code = main(argv)
        finally:
            sys.stdout = old_out
        return code, buf.getvalue()

    def test_version(self):
        code, out = self.capture(["--version"])
        self.assertEqual(code, 0)
        self.assertIn("0.1.0", out)

    def test_health(self):
        # Supply a config via overrides by writing a minimal JSON to stdin? Instead use default config and just run health.
        code, out = self.capture(["--health"])
        self.assertEqual(code, 0)

    def test_run_and_save_transcript(self):
        # Use a temp config with our mock agents
        with tempfile.TemporaryDirectory() as tmp:
            cfg_path = Path(tmp) / "cfg.json"
            data = {
                "agents": [
                    {"id": "m1", "type": "cli_mock"},
                    {"id": "m2", "type": "cli_mock"},
                ],
                "output": {"save_transcript": False},
            }
            cfg_path.write_text(json.dumps(data), encoding="utf-8")
            code, out = self.capture([
                "do something",
                "--rounds", "0",
                "--format", "json",
                "--config", str(cfg_path),
            ])
        self.assertEqual(code, 0)
        self.assertIn("FREE-MAD result", out)
        self.assertIn("Final score:", out)
        self.assertIn("Rounds:", out)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
