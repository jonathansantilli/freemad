import unittest

from freemad import load_config
from freemad import AgentFactory
from freemad import bootstrap as agent_bootstrap  # registers built-ins


class TestAgentRegistryFactory(unittest.TestCase):
    def test_factory_builds_enabled_agents(self):
        cfg = load_config()
        # ensure built-ins are registered
        agent_bootstrap.register_builtin_agents()

        factory = AgentFactory(cfg)
        agents = factory.build_all()
        self.assertIn("claude", agents)
        self.assertIn("codex", agents)
        # Types are the built-in adapters
        self.assertEqual(agents["claude"].agent_cfg.type, "claude_code")
        self.assertEqual(agents["codex"].agent_cfg.type, "openai_codex")

    def test_disabled_agents_are_skipped(self):
        cfg = load_config(
            overrides={
                "agents": [
                    {"id": "a", "type": "claude_code", "enabled": False},
                    {"id": "b", "type": "openai_codex", "enabled": True},
                ]
            }
        )
        agent_bootstrap.register_builtin_agents()
        factory = AgentFactory(cfg)
        agents = factory.build_all()
        self.assertNotIn("a", agents)
        self.assertIn("b", agents)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
