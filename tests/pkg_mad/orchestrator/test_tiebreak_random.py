import random
import unittest

from freemad import load_config
from freemad import Orchestrator
from freemad import register_agent
from freemad import Agent, AgentResponse, CritiqueResponse, Metadata
from freemad import compute_answer_id


class StaticA(Agent):
    def generate(self, requirement: str) -> AgentResponse:
        s = "ANS_X"
        return AgentResponse(self.agent_cfg.id, s, "r", compute_answer_id(s), Metadata())

    def critique_and_refine(self, requirement: str, own_response: str, peer_responses):
        return CritiqueResponse(self.agent_cfg.id, __import__('freemad.types').types.Decision.KEEP, False, own_response, "r", compute_answer_id(own_response), Metadata())


class StaticB(Agent):
    def generate(self, requirement: str) -> AgentResponse:
        s = "ANS_Y"
        return AgentResponse(self.agent_cfg.id, s, "r", compute_answer_id(s), Metadata())

    def critique_and_refine(self, requirement: str, own_response: str, peer_responses):
        return CritiqueResponse(self.agent_cfg.id, __import__('freemad.types').types.Decision.KEEP, False, own_response, "r", compute_answer_id(own_response), Metadata())


class TestTieBreakRandom(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        register_agent("static_a", StaticA)
        register_agent("static_b", StaticB)

    def test_random_tiebreak(self):
        seed = 424242
        cfg = load_config(overrides={
            "agents": [
                {"id": "a", "type": "static_a"},
                {"id": "b", "type": "static_b"},
            ],
            "scoring": {"tie_break": "random", "random_seed": seed},
        })
        o = Orchestrator(cfg)
        out = o.run("task", max_rounds=1)
        # Compute expected by simulating the same random choice over sorted ids
        ids = sorted(list(out["scores"].keys()))
        expected = random.Random(seed).choice(ids)
        self.assertEqual(out["final_answer_id"], expected)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
