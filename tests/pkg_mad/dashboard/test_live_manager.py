import time
import unittest
from queue import Empty

from freemad import Agent, AgentResponse, CritiqueResponse, Metadata
from freemad import Decision, compute_answer_id, load_config, register_agent
from freemad import RunEventKind
from freemad.dashboard.live_manager import LiveRunManager


class _LMKeepAgent(Agent):
    def generate(self, requirement: str) -> AgentResponse:
        sol = f"SOLUTION_{self.agent_cfg.id}"
        return AgentResponse(
            agent_id=self.agent_cfg.id,
            solution=sol,
            reasoning="gen",
            answer_id=compute_answer_id(sol),
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


class TestLiveRunManager(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        register_agent("live_keep", _LMKeepAgent)

    def test_start_run_and_receive_events(self) -> None:
        cfg = load_config(
            overrides={
                "agents": [
                    {"id": "a1", "type": "live_keep"},
                    {"id": "a2", "type": "live_keep"},
                ],
                "deadlines": {"soft_timeout_ms": 50, "hard_timeout_ms": 100, "min_agents": 2},
                "budget": {"max_total_time_sec": 10, "max_round_time_sec": 2, "max_agent_time_sec": 2},
            }
        )
        mgr = LiveRunManager()
        run_id = mgr.start_run(cfg, "do something", max_rounds=1)
        q = mgr.get_queue(run_id)
        self.assertIsNotNone(q)

        kinds = []
        deadline = time.time() + 5.0
        while time.time() < deadline:
            try:
                ev = q.get(timeout=0.2)  # type: ignore[union-attr]
            except Empty:
                if mgr.is_completed(run_id):
                    break
                continue
            kinds.append(ev.kind)
            if ev.kind in (RunEventKind.RUN_COMPLETED, RunEventKind.RUN_FAILED, RunEventKind.RUN_BUDGET_EXCEEDED):
                break

        self.assertIn(RunEventKind.RUN_STARTED, kinds)
        self.assertTrue(
            any(k in (RunEventKind.RUN_COMPLETED, RunEventKind.RUN_FAILED, RunEventKind.RUN_BUDGET_EXCEEDED) for k in kinds)
        )
        self.assertTrue(mgr.is_completed(run_id))


if __name__ == "__main__":  # pragma: no cover
    unittest.main()

