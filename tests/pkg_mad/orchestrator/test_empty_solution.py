import unittest

from freemad import load_config
from freemad import Orchestrator
from freemad import compute_answer_id
from freemad import Agent, AgentResponse, CritiqueResponse, Metadata
from freemad import Decision
from freemad import register_agent


class MockEmptyAgent(Agent):
    def generate(self, requirement: str) -> AgentResponse:
        txt = ""  # intentionally empty
        return AgentResponse(
            agent_id=self.agent_cfg.id,
            solution=txt,
            reasoning="",
            answer_id=compute_answer_id(txt),
            metadata=Metadata(),
        )

    def critique_and_refine(self, requirement: str, own_response: str, peer_responses):
        # Always keep whatever we have (still empty)
        return CritiqueResponse(
            agent_id=self.agent_cfg.id,
            decision=Decision.KEEP,
            changed=False,
            solution=own_response,
            reasoning="keep",
            answer_id=compute_answer_id(own_response),
            metadata=Metadata(),
        )


class MockNonEmptyKeep(Agent):
    def __init__(self, cfg, agent_cfg):
        super().__init__(cfg, agent_cfg)
        self._sol = f"SOLUTION_{agent_cfg.id.upper()}"

    def generate(self, requirement: str) -> AgentResponse:
        txt = self._sol
        return AgentResponse(
            agent_id=self.agent_cfg.id,
            solution=txt,
            reasoning="gen",
            answer_id=compute_answer_id(txt),
            metadata=Metadata(),
        )

    def critique_and_refine(self, requirement: str, own_response: str, peer_responses):
        return CritiqueResponse(
            agent_id=self.agent_cfg.id,
            decision=Decision.KEEP,
            changed=False,
            solution=own_response,
            reasoning="keep",
            answer_id=compute_answer_id(own_response),
            metadata=Metadata(),
        )


class TestEmptySolutionHandling(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        register_agent("mock_empty", MockEmptyAgent)
        register_agent("mock_nonempty_keep", MockNonEmptyKeep)

    def test_empty_initial_is_not_selected(self):
        cfg = load_config(
            overrides={
                "agents": [
                    {"id": "empty", "type": "mock_empty"},
                    {"id": "full", "type": "mock_nonempty_keep"},
                ],
                # make scoring deterministic and simple
                "scoring": {"normalize": True},
            }
        )
        orch = Orchestrator(cfg)
        out = orch.run("do Z", max_rounds=1)
        # Final solution should not be empty
        self.assertTrue(out["final_solution"].strip())
        # Winner must be the non-empty agent
        self.assertEqual(set(out["winning_agents"]), {"full"})
        # Ensure empty answer does not influence scoring (absent or strictly lower)
        scores = out["scores"]
        empty_id = compute_answer_id("")
        if empty_id in scores:
            self.assertLess(scores[empty_id], max(scores.values()))


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
