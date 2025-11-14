import unittest

from freemad import load_config
from freemad import Orchestrator
from freemad import Agent, AgentResponse, CritiqueResponse, Metadata
from freemad import Decision
from freemad import register_agent
from freemad import compute_answer_id


class MockStaticAgent(Agent):
    def __init__(self, cfg, agent_cfg, text: str):
        super().__init__(cfg, agent_cfg)
        self.text = text

    def generate(self, requirement: str) -> AgentResponse:
        return AgentResponse(
            agent_id=self.agent_cfg.id,
            solution=self.text,
            reasoning="gen",
            answer_id=compute_answer_id(self.text),
            metadata=Metadata(),
        )

    def critique_and_refine(self, requirement: str, own_response: str, peer_responses):
        # always keep
        return CritiqueResponse(
            agent_id=self.agent_cfg.id,
            decision=Decision.KEEP,
            changed=False,
            solution=own_response,
            reasoning="keep",
            answer_id=compute_answer_id(own_response),
            metadata=Metadata(),
        )


class TestValidationTiebreak(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # we bind two different types to allow distinct config entries
        register_agent("mock_static1", lambda cfg, acfg: MockStaticAgent(cfg, acfg, "SAFE_ANSWER"))
        register_agent("mock_static2", lambda cfg, acfg: MockStaticAgent(cfg, acfg, "LEAK sk-TEST-KEY"))

    def test_tie_broken_by_validator_confidence(self):
        # Equal scores: both keep; Security validator should penalize the one with key-like token
        cfg = load_config(
            overrides={
                "agents": [
                    {"id": "safe", "type": "mock_static1"},
                    {"id": "leaky", "type": "mock_static2"},
                ],
                "deadlines": {"soft_timeout_ms": 100, "hard_timeout_ms": 200, "min_agents": 2},
            }
        )
        orch = Orchestrator(cfg)
        out = orch.run("do Z", max_rounds=1)
        # both answers exist; pick SAFE_ANSWER via higher validator confidence
        self.assertIn("validator_confidence", out)
        confidences = out["validator_confidence"]
        # Identify which answer_id is safe
        ans_to_text = {t["agents"][aid]["response"]["answer_id"]: t["agents"][aid]["response"]["solution"] for t in out["transcript"] if t["round"] == 0 for aid in t["agents"]}
        # final must be SAFE_ANSWER
        final_id = out["final_answer_id"]
        self.assertEqual(out["final_solution"], "SAFE_ANSWER")
        # ensure confidence higher for the chosen answer
        other_id = [k for k in confidences.keys() if k != final_id][0]
        self.assertGreater(confidences[final_id], confidences[other_id])


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
