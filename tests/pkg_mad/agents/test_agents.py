import sys
import unittest

from freemad import load_config
from freemad import AgentFactory
from freemad import bootstrap as agent_bootstrap


class TestAgentHealth(unittest.TestCase):
    def setUp(self):
        agent_bootstrap.register_builtin_agents()

    def test_health_without_cli_command(self):
        cfg = load_config()
        factory = AgentFactory(cfg)
        agents = factory.build_all()
        h1 = agents["claude"].health()
        h2 = agents["codex"].health()
        self.assertFalse(h1.available)
        self.assertIn("cli_command", h1.message)
        self.assertFalse(h2.available)

    def test_health_with_allowed_interpreter(self):
        """A configured, allowlisted, present executable reports available with a version.

        The stand-in is the interpreter running these tests. A bare "python" only
        resolves when a venv is on PATH (macOS ships no /usr/bin/python), which made this
        test assert an accident of `poetry run` rather than a property of health().
        """
        exe = sys.executable
        cfg = load_config(
            overrides={
                "agents": [
                    {"id": "py", "type": "claude_code", "cli_command": exe},
                    {"id": "py2", "type": "openai_codex", "cli_command": exe},
                ],
                "security": {"cli_allowed_commands": [exe]},
            }
        )
        factory = AgentFactory(cfg)
        agents = factory.build_all()
        for a in agents.values():
            health = a.health()
            self.assertEqual(health.command, exe)  # allowed, and reported as configured
            self.assertTrue(health.available, health.message)
            self.assertTrue(health.version is None or "Python" in health.version)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
