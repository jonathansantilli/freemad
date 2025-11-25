from __future__ import annotations

import random
import unittest

from freemad import Orchestrator, Agent, AgentResponse, CritiqueResponse, Metadata, Decision, compute_answer_id, load_config, register_agent
from freemad.config import Config, AgentConfig


class FixedAgent(Agent):
    def __init__(self, cfg: Config, agent_cfg: AgentConfig, solution: str) -> None:
        super().__init__(cfg, agent_cfg)
        self.solution = solution

    def generate(self, requirement: str) -> AgentResponse:
        return AgentResponse(self.agent_cfg.id, self.solution, "r", compute_answer_id(self.solution), Metadata())

    def critique_and_refine(self, requirement: str, own_response: str, peer_responses):  # type: ignore[override]
        return CritiqueResponse(self.agent_cfg.id, Decision.KEEP, False, own_response, "r", compute_answer_id(own_response), Metadata())


class BudgetlessAgent(Agent):
    def generate(self, requirement: str) -> AgentResponse:
        return AgentResponse(self.agent_cfg.id, "X", "r", compute_answer_id("X"), Metadata(tokens={"prompt": 0, "output": 10_000}))

    def critique_and_refine(self, requirement: str, own_response: str, peer_responses):
        return CritiqueResponse(self.agent_cfg.id, Decision.KEEP, False, own_response, "r", compute_answer_id(own_response), Metadata(tokens={"prompt": 0, "output": 10_000}))


def _make_fixed_a(cfg: Config, agent_cfg: AgentConfig) -> FixedAgent:
    return FixedAgent(cfg, agent_cfg, "AAA")


def _make_fixed_b(cfg: Config, agent_cfg: AgentConfig) -> FixedAgent:
    return FixedAgent(cfg, agent_cfg, "BBB")


class TestTieBreakBudgetEdges(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        register_agent("fixed_a", _make_fixed_a)  # type: ignore[arg-type]
        register_agent("fixed_b", _make_fixed_b)  # type: ignore[arg-type]
        register_agent("budgetless", BudgetlessAgent)

    def test_deterministic_tiebreak_prefers_lexicographic(self):
        cfg = load_config(
            overrides={
                "agents": [
                    {"id": "a", "type": "fixed_a"},
                    {"id": "b", "type": "fixed_b"},
                ],
                "scoring": {"tie_break": "deterministic"},
            }
        )
        orch = Orchestrator(cfg)
        out = orch.run("task", max_rounds=0)
        ids = sorted(list(out["scores"].keys()))
        self.assertEqual(out["final_answer_id"], ids[0])

    def test_random_tiebreak_uses_seed(self):
        seed = 999
        cfg = load_config(
            overrides={
                "agents": [
                    {"id": "a", "type": "fixed_a"},
                    {"id": "b", "type": "fixed_b"},
                ],
                "scoring": {"tie_break": "random", "random_seed": seed},
            }
        )
        orch = Orchestrator(cfg)
        out = orch.run("task", max_rounds=0)
        ids = sorted(list(out["scores"].keys()))
        expected = random.Random(seed).choice(ids)
        self.assertEqual(out["final_answer_id"], expected)

    def test_total_token_budget_exceeded_raises(self):
        cfg = load_config(
            overrides={
                "agents": [
                    {"id": "x", "type": "budgetless"},
                    {"id": "y", "type": "budgetless"},
                ],
                "budget": {"enforce_total_tokens": True, "max_total_tokens": 5},
            }
        )
        orch = Orchestrator(cfg)
        with self.assertRaises(Exception):
            orch.run("task", max_rounds=0)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
