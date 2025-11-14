import time
import unittest

from freemad import load_config
from freemad import Orchestrator
from freemad import compute_answer_id
from freemad import Agent, AgentResponse, CritiqueResponse, Metadata
from freemad import Decision
from freemad import register_agent


class MockKeepAgent(Agent):
    def __init__(self, cfg, agent_cfg, solution_text: str = ""):
        super().__init__(cfg, agent_cfg)
        # encode default solution per id for determinism
        self._sol = solution_text or f"SOLUTION_{agent_cfg.id.upper()}"

    def generate(self, requirement: str) -> AgentResponse:
        return AgentResponse(
            agent_id=self.agent_cfg.id,
            solution=self._sol,
            reasoning="gen",
            answer_id=compute_answer_id(self._sol),
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


class MockReviseToFirstPeer(Agent):
    def __init__(self, cfg, agent_cfg, initial_text: str = ""):
        super().__init__(cfg, agent_cfg)
        self._sol = initial_text or f"INIT_{agent_cfg.id}"

    def generate(self, requirement: str) -> AgentResponse:
        return AgentResponse(
            agent_id=self.agent_cfg.id,
            solution=self._sol,
            reasoning="gen",
            answer_id=compute_answer_id(self._sol),
            metadata=Metadata(),
        )

    def critique_and_refine(self, requirement: str, own_response: str, peer_responses):
        if peer_responses:
            new = peer_responses[0]
            return CritiqueResponse(
                agent_id=self.agent_cfg.id,
                decision=Decision.REVISE,
                changed=True,
                solution=new,
                reasoning="adopt best peer",
                answer_id=compute_answer_id(new),
                metadata=Metadata(),
            )
        return CritiqueResponse(
            agent_id=self.agent_cfg.id,
            decision=Decision.KEEP,
            changed=False,
            solution=own_response,
            reasoning="no peers",
            answer_id=compute_answer_id(own_response),
            metadata=Metadata(),
        )


class MockDelayKeep(Agent):
    def __init__(self, cfg, agent_cfg):
        super().__init__(cfg, agent_cfg)
        self.delay_s = 0.0
        self._sol = f"DELAY_{agent_cfg.id}"

    def generate(self, requirement: str) -> AgentResponse:
        time.sleep(0.01)
        return AgentResponse(
            agent_id=self.agent_cfg.id,
            solution=self._sol,
            reasoning="gen",
            answer_id=compute_answer_id(self._sol),
            metadata=Metadata(),
        )

    def critique_and_refine(self, requirement: str, own_response: str, peer_responses):
        time.sleep(self.delay_s)
        return CritiqueResponse(
            agent_id=self.agent_cfg.id,
            decision=Decision.KEEP,
            changed=False,
            solution=own_response,
            reasoning="keep",
            answer_id=compute_answer_id(own_response),
            metadata=Metadata(),
        )


class TestOrchestrator(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        register_agent("mock_keep", MockKeepAgent)
        register_agent("mock_revise", MockReviseToFirstPeer)
        register_agent("mock_delay_keep", MockDelayKeep)

    def test_two_agents_flow_with_revision(self):
        cfg = load_config(
            overrides={
                "agents": [
                    {"id": "a1", "type": "mock_keep"},
                    {"id": "a2", "type": "mock_revise"},
                ],
            }
        )
        orch = Orchestrator(cfg)
        out = orch.run("do X", max_rounds=1)
        self.assertEqual(len(out["transcript"]), 2)  # round 0 + round 1
        crit = out["transcript"][1]
        self.assertEqual(crit["type"], "critique")
        # peers captured
        self.assertEqual(crit["agents"]["a1"]["peers_assigned_count"], 1)
        self.assertEqual(crit["agents"]["a2"]["peers_assigned_count"], 1)
        # winner is the solution from a1 adopted by a2
        winning = set(out["winning_agents"])
        self.assertEqual(winning, {"a1", "a2"})
        # score expectations
        scores = out["scores"]
        self.assertEqual(len(scores), 2)
        # A1 answer should have higher normalized score than A2's original
        # find ids
        ans_ids = list(scores.keys())
        # Determine which is adopted (both agents end on the same)
        # The adopted answer has 2 contributors and higher raw, but normalized should still exceed the penalized old answer
        adopted_score = max(scores.values())
        other_score = min(scores.values())
        self.assertGreater(adopted_score, other_score)

    def test_deadline_soft_then_hard_not_hit(self):
        # soft=100ms, hard=300ms; one agent delays 150ms, so soft is hit but hard is not
        cfg = load_config(
            overrides={
                "agents": [
                    {"id": "fast", "type": "mock_delay_keep", "config": {}, "timeout": 5},
                    {"id": "slow", "type": "mock_delay_keep", "config": {}, "timeout": 5},
                ],
                "deadlines": {"soft_timeout_ms": 100, "hard_timeout_ms": 300, "min_agents": 2},
            }
        )
        # inject delays by modifying the constructed agents after factory
        orch = Orchestrator(cfg)
        orch.agents["fast"].delay_s = 0.02
        orch.agents["slow"].delay_s = 0.15
        out = orch.run("do Y", max_rounds=1)
        crit = out["transcript"][1]
        self.assertTrue(crit["deadline_hit_soft"])  # fast done, slow not => quorum unmet at soft
        # Ensure hard not hit
        self.assertFalse(crit["deadline_hit_hard"])  # completes by 300ms

    def test_progress_multiple_rounds(self):
        # Ensure orchestrator runs exactly N critique rounds when budgets permit
        cfg = load_config(
            overrides={
                "agents": [
                    {"id": "a1", "type": "mock_keep"},
                    {"id": "a2", "type": "mock_keep"},
                ],
                "deadlines": {"soft_timeout_ms": 50, "hard_timeout_ms": 100, "min_agents": 2},
                "budget": {"max_total_time_sec": 10, "max_round_time_sec": 2, "max_agent_time_sec": 2},
            }
        )
        orch = Orchestrator(cfg)
        out = orch.run("do Z", max_rounds=3)
        # Transcript contains 1 generation + 3 critique rounds
        self.assertEqual(len(out["transcript"]), 4)

    def test_early_stop_reason_round_budget(self):
        # Use delayed agents and a tight per-round budget to force early stop
        cfg = load_config(
            overrides={
                "agents": [
                    {"id": "slow1", "type": "mock_delay_keep", "timeout": 5},
                    {"id": "slow2", "type": "mock_delay_keep", "timeout": 5},
                ],
                # Deadlines permit the work; budget causes the stop
                "deadlines": {"soft_timeout_ms": 200, "hard_timeout_ms": 400, "min_agents": 2},
                "budget": {"max_total_time_sec": 10, "max_round_time_sec": 0.02, "max_agent_time_sec": 2},
            }
        )
        orch = Orchestrator(cfg)
        orch.agents["slow1"].delay_s = 0.05
        orch.agents["slow2"].delay_s = 0.05
        out = orch.run("do Z", max_rounds=5)
        # Should have stopped early due to round budget
        self.assertEqual(out.get("early_stop_reason"), "round_time_budget_exceeded")
        # 1 generation + 1 critique before stopping
        self.assertEqual(len(out["transcript"]), 2)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
