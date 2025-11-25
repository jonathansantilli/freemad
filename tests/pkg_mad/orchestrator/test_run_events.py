import unittest

from freemad import Orchestrator, load_config
from freemad import Agent, AgentResponse, CritiqueResponse, Metadata, compute_answer_id
from freemad import Decision
from freemad import RunEvent, RunEventKind, RunObserver, register_agent


class _CaptureObserver(RunObserver):
    def __init__(self) -> None:
        self.events: list[RunEvent] = []

    def on_event(self, event: RunEvent) -> None:
        self.events.append(event)


class _StaticKeepAgent(Agent):
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


class TestRunEvents(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        register_agent("events_keep", _StaticKeepAgent)

    def setUp(self) -> None:
        self.cfg = load_config(
            overrides={
                "agents": [
                    {"id": "a1", "type": "events_keep"},
                    {"id": "a2", "type": "events_keep"},
                ],
                "deadlines": {"soft_timeout_ms": 50, "hard_timeout_ms": 100, "min_agents": 2},
                "budget": {"max_total_time_sec": 10, "max_round_time_sec": 2, "max_agent_time_sec": 2},
            }
        )

    def test_events_emitted_basic_flow(self) -> None:
        observer = _CaptureObserver()
        orch = Orchestrator(self.cfg, observer=observer)
        result = orch.run("do something", max_rounds=1)
        self.assertIn("final_answer_id", result)

        kinds = [e.kind for e in observer.events]
        self.assertIn(RunEventKind.RUN_STARTED, kinds)
        self.assertIn(RunEventKind.RUN_COMPLETED, kinds)
        self.assertIn(RunEventKind.ROUND_STARTED, kinds)
        self.assertIn(RunEventKind.ROUND_COMPLETED, kinds)
        self.assertIn(RunEventKind.AGENT_GENERATE_STARTED, kinds)
        self.assertIn(RunEventKind.AGENT_GENERATE_FINISHED, kinds)
        self.assertIn(RunEventKind.SCORES_UPDATED, kinds)
        self.assertIn(RunEventKind.FINAL_ANSWER_SELECTED, kinds)
        self.assertIn(RunEventKind.AGENT_CRITIQUE_STARTED, kinds)
        self.assertIn(RunEventKind.AGENT_CRITIQUE_FINISHED, kinds)

        # All events share the same run_id
        run_ids = {e.run_id for e in observer.events}
        self.assertEqual(len(run_ids), 1)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
