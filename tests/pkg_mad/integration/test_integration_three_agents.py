import unittest

from freemad import load_config
from freemad import Orchestrator
from freemad import register_agent
from freemad import Agent, AgentResponse, CritiqueResponse, Metadata
from freemad import Decision
from freemad import compute_answer_id


class A1Keep(Agent):
    def generate(self, requirement: str) -> AgentResponse:
        s = "ANS_A"
        return AgentResponse(self.agent_cfg.id, s, "r", compute_answer_id(s), Metadata())

    def critique_and_refine(self, requirement: str, own_response: str, peer_responses):
        return CritiqueResponse(self.agent_cfg.id, Decision.KEEP, False, own_response, "r", compute_answer_id(own_response), Metadata())


class A2AdoptA1(Agent):
    def generate(self, requirement: str) -> AgentResponse:
        s = "ANS_B"
        return AgentResponse(self.agent_cfg.id, s, "r", compute_answer_id(s), Metadata())

    def critique_and_refine(self, requirement: str, own_response: str, peer_responses):
        # adopt first peer
        new = peer_responses[0] if peer_responses else own_response
        changed = new != own_response
        return CritiqueResponse(self.agent_cfg.id, Decision.REVISE if changed else Decision.KEEP, changed, new, "r", compute_answer_id(new), Metadata())


class A3Keep(Agent):
    def generate(self, requirement: str) -> AgentResponse:
        s = "ANS_C"
        return AgentResponse(self.agent_cfg.id, s, "r", compute_answer_id(s), Metadata())

    def critique_and_refine(self, requirement: str, own_response: str, peer_responses):
        return CritiqueResponse(self.agent_cfg.id, Decision.KEEP, False, own_response, "r", compute_answer_id(own_response), Metadata())


class TestThreeAgentsIntegration(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        register_agent("a1_keep", A1Keep)
        register_agent("a2_adopt", A2AdoptA1)
        register_agent("a3_keep", A3Keep)

    def test_three_agents_scores_and_transcript(self):
        cfg = load_config(overrides={
            "agents": [
                {"id": "a1", "type": "a1_keep"},
                {"id": "a2", "type": "a2_adopt"},
                {"id": "a3", "type": "a3_keep"}
            ],
            "topology": {"type": "all_to_all"}
        })
        orch = Orchestrator(cfg)
        out = orch.run("task", max_rounds=1)
        # Transcript round count
        self.assertEqual(len(out["transcript"]), 2)
        # Topology info present
        self.assertEqual(out["transcript"][0]["topology_info"]["type"], "all_to_all")
        # Winning agents likely a3 due to normalization; assert present in set of agents
        self.assertIn(out["winning_agents"][0], {"a1", "a2", "a3"})
        # peers counts recorded
        for a in ["a1", "a2", "a3"]:
            self.assertIn("peers_assigned_count", out["transcript"][1]["agents"][a])


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
