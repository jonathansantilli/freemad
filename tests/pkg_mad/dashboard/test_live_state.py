import unittest

from freemad import Decision, RoundType
from freemad import RunEvent, RunEventKind
from freemad.dashboard.live_state import (
    AgentStatus,
    apply_event,
    initial_snapshot,
)


class TestLiveState(unittest.TestCase):
    def test_basic_sequence_updates_snapshot(self) -> None:
        run_id = "run-1"
        snap = initial_snapshot(run_id)

        # Round start
        e_round = RunEvent(
            kind=RunEventKind.ROUND_STARTED,
            run_id=run_id,
            ts_ms=0,
            round_index=0,
            round_type=RoundType.GENERATION,
        )
        snap = apply_event(snap, e_round)
        self.assertEqual(snap.round_index, 0)
        self.assertEqual(snap.round_type, RoundType.GENERATION)

        # Agent generate started/finished
        e_start = RunEvent(
            kind=RunEventKind.AGENT_GENERATE_STARTED,
            run_id=run_id,
            ts_ms=1,
            round_index=0,
            round_type=RoundType.GENERATION,
            agent_id="a1",
        )
        snap = apply_event(snap, e_start)
        self.assertIn("a1", snap.agents)
        self.assertEqual(snap.agents["a1"].status, AgentStatus.GENERATING)

        e_finish = RunEvent(
            kind=RunEventKind.AGENT_GENERATE_FINISHED,
            run_id=run_id,
            ts_ms=2,
            round_index=0,
            round_type=RoundType.GENERATION,
            agent_id="a1",
            answer_id="ans-1",
            decision=Decision.KEEP,
        )
        snap = apply_event(snap, e_finish)
        self.assertEqual(snap.agents["a1"].status, AgentStatus.WAITING)
        self.assertEqual(snap.agents["a1"].current_answer_id, "ans-1")

        # Score update
        e_scores = RunEvent(
            kind=RunEventKind.SCORES_UPDATED,
            run_id=run_id,
            ts_ms=3,
            round_index=0,
            round_type=RoundType.GENERATION,
            scores={"ans-1": 10.0},
            holders={"ans-1": ["a1"]},
        )
        snap = apply_event(snap, e_scores)
        self.assertEqual(snap.scores["ans-1"], 10.0)
        self.assertEqual(snap.holders["ans-1"], ["a1"])

        # Critique started/finished
        e_c_start = RunEvent(
            kind=RunEventKind.AGENT_CRITIQUE_STARTED,
            run_id=run_id,
            ts_ms=3,
            round_index=1,
            round_type=RoundType.CRITIQUE,
            agent_id="a1",
        )
        snap = apply_event(snap, e_c_start)
        self.assertEqual(snap.agents["a1"].status, AgentStatus.CRITIQUING)

        e_c_finish = RunEvent(
            kind=RunEventKind.AGENT_CRITIQUE_FINISHED,
            run_id=run_id,
            ts_ms=4,
            round_index=1,
            round_type=RoundType.CRITIQUE,
            agent_id="a1",
            answer_id="ans-1b",
            decision=Decision.REVISE,
            changed=True,
        )
        snap = apply_event(snap, e_c_finish)
        self.assertEqual(snap.agents["a1"].status, AgentStatus.WAITING)
        self.assertEqual(snap.agents["a1"].current_answer_id, "ans-1b")
        self.assertEqual(snap.agents["a1"].changes_count, 1)

        # Final answer and completion
        e_final = RunEvent(
            kind=RunEventKind.FINAL_ANSWER_SELECTED,
            run_id=run_id,
            ts_ms=5,
            final_answer_id="ans-1",
            winning_agents=["a1"],
        )
        snap = apply_event(snap, e_final)
        self.assertEqual(snap.final_answer_id, "ans-1")
        self.assertEqual(snap.winning_agents, ["a1"])

        e_done = RunEvent(
            kind=RunEventKind.RUN_COMPLETED,
            run_id=run_id,
            ts_ms=6,
        )
        snap = apply_event(snap, e_done)
        self.assertTrue(snap.completed)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
