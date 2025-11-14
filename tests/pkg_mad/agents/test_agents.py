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

    def test_health_with_allowed_python(self):
        cfg = load_config(
            overrides={
                "agents": [
                    {"id": "py", "type": "claude_code", "cli_command": "python"},
                    {"id": "py2", "type": "openai_codex", "cli_command": "python"},
                ],
                "security": {"cli_allowed_commands": ["python"]},
            }
        )
        factory = AgentFactory(cfg)
        agents = factory.build_all()
        for a in agents.values():
            health = a.health()
            self.assertTrue(health.command)
            self.assertIn(health.command, ["python"])  # allowed
            # python --version should succeed quickly in CI
            self.assertTrue(health.available)
            self.assertTrue(health.version is None or "Python" in health.version)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
